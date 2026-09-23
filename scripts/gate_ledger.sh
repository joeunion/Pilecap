#!/usr/bin/env bash
# The gate's verdict ledger — sourced by check.sh and the pre-push hook. BASH ONLY:
# sourced into an interactive zsh, `local path` ties to $PATH and every helper
# dies silently.
#
# The gate's verdict is a property of a TREE, not of who asked for it. A full
# green run records the content address of what it measured; a later stage
# about to measure identical bytes honours the verdict instead of re-deriving a
# deterministic result. Three properties keep it honest:
#
#  1. THE KEY IS WHAT WAS MEASURED, not what was committed: the working tree's
#     content address (tracked + untracked-non-ignored files), computed through
#     a TEMPORARY index so neither the real index nor the tree is touched, MINUS
#     the paths a leg DECLARES it derives (`gate__derived_tree_paths`). On a
#     clean tree with nothing declared — which is this repository today — it
#     equals `git rev-parse HEAD^{tree}`, so a verdict earned before a commit
#     vouches for the commit after it; with a declaration live it equals that
#     tree with the declared subtrees removed, which is the SAME key on every
#     box rather than a different one on each.
#  2. A VERDICT IS ONLY EARNED BY A COMPLETE GREEN FULL RUN. Exit 1 records
#     nothing (a red run re-explains itself every time); exit 2 records nothing
#     and never can. Neither partial mode records a FULL verdict here: a partial
#     run must never vouch for a whole tree. `--fast` records nothing anywhere
#     at all; `--loop` banks a verdict of its OWN, at its own key, in THE LOOP
#     LEDGER further down — a strictly narrower claim, in a different file, that
#     nothing reading this section can mistake for one of these rows.
#  3. A VERDICT NAMES A TREE THAT STILL EXISTED WHEN THE RUN ENDED: measured at
#     start AND end; if they differ (agents edit concurrently), the run's pass
#     still prints but earns no carry-forward.
#
# Trust class, stated: this is a local file an agent could echo a line into,
# exactly as `git push --no-verify` is one flag away. The hooks were never a
# security boundary; CI re-runs everything from a fresh checkout.
#
# The run log beside it answers "what happened to a full run that earned no
# verdict" — a red leg, exit 2, a kill at the tool's ten-minute ceiling, or a
# tree edited mid-run — one line per unsettled run, keyed by starting tree, so
# the next agent reads what happened instead of guessing from an exit code.

# THE REFUSAL SEAM — scripts/gate_refuse.sh, sourced by this library's own
# directory and guarded against a second source. This library refuses in notes
# rather than in `!!` headlines, so it takes the seam for its CALLERS: check.sh
# and githooks/pre-push both reach it through here, before anything else is
# sourced.
# shellcheck source=scripts/gate_refuse.sh
if [ -z "${GATE_REFUSE_SOURCED:-}" ]; then
    case "${BASH_SOURCE[0]:-}" in
    */*) . "${BASH_SOURCE[0]%/*}/gate_refuse.sh" ;;
    *) . scripts/gate_refuse.sh ;;
    esac
fi

GATE_LEDGER_SCHEMA=v1

# ---- who asked -------------------------------------------------------
#
# THE QUESTION THE LEDGER COULD NOT ANSWER. The doctrine is one full gate per
# push. The measurement is 330 full runs in six days. Both of those can be true
# — a quality rung must run the full gate, a PM banks a verdict before a merge
# window, a red push re-runs — but until now every recorded line looked
# identical, so the gap between doctrine and population was un-auditable: nobody
# could say which of those 330 were the wall doing its job and which were
# something else. So each full run now records WHO ASKED.
#
# MEASUREMENT, NOT ENFORCEMENT, and deliberately so this cycle. No run is
# refused for its caller, no caller is privileged, and an unrecognised value is
# recorded as `unstated` with a note rather than rejected. First you count the
# population; only then is there anything to argue about refusing.
#
# THE VOCABULARY IS CLOSED, because a free-text field is a field nobody can
# group by:
#
#   push-wall     the pre-push hook ran it. The doctrine's own case.
#   quality-rung  a builder whose rung changes `quality/**` or the dependencies,
#                 where the full gate uniquely binds (rung-execution §3's two
#                 named exceptions).
#   pm-bank       the PM banking a verdict for a tree ahead of a push or a merge
#                 window.
#   unstated      nobody said. The default, and NOT a synonym for "wrong" —
#                 every line written before this field existed is this.
#
# HOW IT IS SET: `DJB_GATE_CALLER=<kind>` in the gate's environment. The
# pre-push hook exports `push-wall` for itself; everything else is the caller
# saying so. It is read at record time, never cached.
#
# WHERE IT IS NOT WRITTEN: `djb-gate-last-full`, which is a duration cache read
# by `gate_run_announce`'s `grep ' green$'` and not part of the population being
# censused. Named here rather than left to be discovered.
GATE_CALLER_KINDS="push-wall quality-rung pm-bank unstated"

# gate_caller — the caller kind for this run, always exactly one token from the
# closed set above, on stdout.
gate_caller() {
    local want=${DJB_GATE_CALLER:-}
    [ -n "$want" ] || {
        printf 'unstated\n'
        return 0
    }
    case " $GATE_CALLER_KINDS " in
    *" $want "*)
        printf '%s\n' "$want"
        return 0
        ;;
    esac
    # Loud, and still recorded. An unknown caller IS unstated — but a typo that
    # silently became `unstated` would be a measurement quietly losing a run.
    echo "  note: DJB_GATE_CALLER='$want' is not one of: $GATE_CALLER_KINDS — recording 'unstated'" >&2
    printf 'unstated\n'
}

# Shared across worktrees on purpose: --git-common-dir is the ONE .git for the
# checkout family, so a verdict earned in one worktree is honoured by another
# measuring identical bytes. Never committed — git does not track its own dir.
gate_local_path() {
    local common
    common=$(git rev-parse --git-common-dir 2>/dev/null) || return 1
    case "$common" in
    /*) ;;
    *) common="$(git rev-parse --show-toplevel)/$common" ;;
    esac
    printf '%s\n' "$common/$1"
}

# THE ONE OVERRIDE, AND IT EXISTS FOR THE DRIVES. This file is SHARED across
# every worktree of one checkout family (`--git-common-dir`, above), which is
# exactly what a drive proving the ledger's own behaviour must not write into: a
# planted row in the real file is a destructive demonstration aimed at found
# state, and rung-execution §2 says a drive builds its own victim. So a drive
# points `DJB_GATE_LEDGER` at a file under its own `mktemp -d` and everything
# that reads or writes a verdict follows it there.
#
# IT IS REFUSED RATHER THAN HONOURED WHEN IT IS RELATIVE, for
# `drive_require_scratch`'s reason one axis over: a relative ledger path
# resolves against whatever directory a caller left behind, and a verdict
# written to a path nobody can name is a verdict nobody can audit.
gate_ledger_path() {
    if [ -n "${DJB_GATE_LEDGER:-}" ]; then
        case "${DJB_GATE_LEDGER}" in
        /*)
            printf '%s\n' "$DJB_GATE_LEDGER"
            return 0
            ;;
        *)
            echo "note: DJB_GATE_LEDGER='${DJB_GATE_LEDGER}' is relative — refusing it." >&2
            return 1
            ;;
        esac
    fi
    gate_local_path djb-gate-verdicts
}
gate_runs_path() { gate_local_path djb-gate-runs; }
gate_last_full_path() { gate_local_path djb-gate-last-full; }

# ---- the tracked paths a leg DERIVES ----------------------------------------
#
# THE SAME DECLARATION MECHANISM AS `loop_env_derived_keys` FURTHER DOWN, ONE
# AXIS OVER: there it is `.env` KEYS that differ per checkout by construction,
# here it is committed PATHS whose bytes differ per BOX by construction.
#
# THE DEFECT IT ANSWERS. A leg that WRITES into the tracked tree on a green run
# moves the very hash the verdict is keyed on, so the gate passes every leg and
# then banks nothing: the run prints `ok: all checks passed` and, a line later,
# `no verdict recorded — the tree changed while the gate ran`, and the next
# stage measures the whole thing again. The sibling platform paid it in full on
# a visual leg that republishes one machine-dependent picture per (fixture x
# width) into a committed directory — seventeen minutes of green vouching for
# nothing.
#
# WHY EXCLUDING IS SAFE HERE AND WOULD NOT BE ELSEWHERE. The danger of an
# exclusion is always the same one: a key that fails to move is a stale green
# with no diff to find it by. That danger needs the excluded bytes to be an
# INPUT to something the gate asks. A declared path is the opposite — a leg's
# OUTPUT, written after the measurement, read only by a human settling a
# dispute. So the declaration is a claim with teeth, and it is the declaring
# leg's job to state it beside its own write: NOTHING MEASURED READS THIS PATH
# BACK. Declare a path any check reads and the ledger will lie. If that ever
# stops being true of a declared path, delete the declaration first.
#
# DERIVED, NEVER TYPED, on both axes — `loop_env_derived_keys`' argument,
# unrepeated: the PATH comes from the writing file's own declaration beside its
# own write, and the FILES scanned are a glob of the places this repository
# keeps the code that runs as a leg, so a new deriver joins by declaring one. A
# hand list here would be a second copy that agrees on the day it is written and
# then goes stale in the direction of a FALSE HIT.
#
# ZERO MEMBERS IS LEGAL, and today it is the whole population: nothing in this
# repository publishes a committed derived artefact. That is the one place this
# fails open rather than closed, and deliberately — nothing declared means
# nothing excluded, which is the key exactly as it was computed before this
# existed. Every OTHER doubt fails closed: an unreadable declaration, a path
# that is not plainly one repository-relative subtree, a path nothing tracks —
# each excludes NOTHING and says so, which costs a re-measure and never a hit on
# an exclusion nobody could verify.

#: The sentinels a DERIVER puts beside its own write. Carried in whatever
#: comment syntax the declaring file speaks, so the leader is stripped rather
#: than matched — and a sentinel is only honoured ON A COMMENT LINE, which is
#: what keeps these two assignments from opening a declaration in the file that
#: defines them. Adjacency would hide it today and stop hiding it the moment
#: somebody puts a line between them.
GATE_TREE_DECL_BEGIN='>>> derived-tree-paths >>>'
GATE_TREE_DECL_END='<<< derived-tree-paths <<<'

#: The globs scanned for the sentinel — where this repository keeps the code
#: that runs as a leg. NOT a list of derivers: a list of where a deriver may
#: declare itself.
#:
#: AND THE PRODUCT'S OWN DRAWERS ARE IN IT (the platform-extension-1 ruling). A product
#: extends this system by DECLARING beside it — `scripts/local/legs/<name>.sh`,
#: `scripts/local/fold.d/<step>.sh` — and a local deriver that writes a
#: committed artefact has exactly the same claim on this exclusion as a template
#: one. Two levels and not a `**`: bash 3.2 has no `globstar`, so a `**` here
#: would be one literal `*` wearing two, matching less than it looks like it
#: matches — which is the silent direction. The whole-tree sweep below NAMES a
#: declaration that lands outside these globs, so a third level is a note and
#: never a void.
GATE_TREE_DECL_SOURCES='scripts/*.sh quality/*.py frontend/scripts/*.sh scripts/local/*.sh scripts/local/*/*.sh'

# gate__derived_tree_paths [root] — the declared derived paths, repository
# relative, one per line, sorted and unique, on stdout.
#
# Exit 0 read cleanly (zero paths is a clean read) · 1 REFUSED, with a note on
# stderr and NOTHING on stdout: the caller excludes nothing and measures the
# whole tree.
#
# THE ENTRY FORM IS `<path> — <reason>` AND THE EM DASH IS LOAD-BEARING, for the
# reason `loop_env_derived_keys` measured: without it a paragraph inside the
# block declares whatever its first word is, and a declaration a paragraph can
# accidentally satisfy is not a declaration. Here a line that is not an entry is
# REFUSED rather than skipped — a block holding prose is a block somebody wrote
# wrong, and the safe answer to that is to exclude nothing and say so.
#
# AND A DECLARATION OUTSIDE THOSE GLOBS IS NAMED, NEVER A VOID (B4.5). The globs
# are where a deriver MAY declare itself; a deriver that declares somewhere else
# declares into nothing — this reader never opens the file, so nothing is
# excluded and, until now, nothing said so. That is the only failure mode here
# that is silent in the direction of a WASTED re-measure rather than a false hit,
# which is exactly why it could sit unnoticed. So the whole tracked tree is swept
# once per read for the opening sentinel, and every hit outside the scanned set
# gets a note on stderr. It is a NOTE and not a refusal: nothing was excluded, so
# the key is the key it always was, and turning a stray comment into an exit
# status would let one misplaced line stop every gate on the box.
#
# THE SAME COMMENT-LINE TEST THE READER APPLIES, and that is what keeps the
# drives out of it: `scripts/tests/test_loop_ledger.sh` writes the sentinel
# inside `echo` arguments when it plants a declaration, and an `echo` line is not
# a comment line. A sweep that matched the bare string would report this
# repository's own drive as a stray declaration on every single run.
gate__derived_tree_paths() {
    local dir=${1:-.} glob f decl line kind body paths="" refused=0 tracked=0
    local scanned=" " rel sf inside stray hits
    for glob in $GATE_TREE_DECL_SOURCES; do
        for f in "$dir"/$glob; do
            [ -r "$f" ] || continue
            rel=${f#"$dir"/}
            scanned="${scanned}${rel} "
        done
    done
    decl=$(
        for glob in $GATE_TREE_DECL_SOURCES; do
            for f in "$dir"/$glob; do
                [ -r "$f" ] || continue
                awk -v b="$GATE_TREE_DECL_BEGIN" -v e="$GATE_TREE_DECL_END" \
                    -v dash="—" -v who="$f" '
                    {
                        lead = $0
                        sub(/^[ \t]*/, "", lead)
                        # A DECLARATION IS A COMMENT. Without this the two
                        # assignments that hold the sentinel strings would open
                        # and close a block in this library itself, and the only
                        # thing keeping that harmless would be that they sit on
                        # consecutive lines.
                        incomment = (substr(lead, 1, 1) == "#" || substr(lead, 1, 1) == "*")
                    }
                    incomment && index($0, b) { on = 1; next }
                    incomment && index($0, e) { on = 0; next }
                    on {
                        line = $0
                        # The comment leader of whatever language declared it.
                        sub(/^[ \t]*[#*][ \t]*/, "", line)
                        sub(/^[ \t]+/, "", line)
                        sub(/[ \t]+$/, "", line)
                        if (line == "") next
                        name = line
                        sub(/[ \t].*$/, "", name)
                        rest = substr(line, length(name) + 1)
                        sub(/^[ \t]+/, "", rest)
                        if (substr(rest, 1, length(dash)) != dash) {
                            print "bad " who ":" FNR " is inside the block and is not `<path> — <reason>`"
                            next
                        }
                        print "ok " name
                    }
                    END {
                        if (on) print "bad " who " opened a declaration and never closed it"
                    }
                ' "$f"
            done
        done
    )
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        kind=${line%% *}
        body=${line#* }
        if [ "$kind" = bad ]; then
            echo "  note: a derived-tree-paths declaration could not be read — $body" >&2
            refused=1
            continue
        fi
        [ "$kind" = ok ] || continue
        # ONE REPOSITORY-RELATIVE SUBTREE AND NOTHING ELSE. `.`, `/` and a `..`
        # escape are what a typo or a copy-paste produces, and obeying one would
        # make every verdict a false hit about a tree nothing measured.
        case "$body" in
        "" | /* | *..* | *" "*) ;;
        [A-Za-z0-9_]*)
            case "$body" in
            *[!A-Za-z0-9._/-]*) ;;
            *)
                tracked=$(git -C "$dir" ls-files -- "$body" 2>/dev/null | awk 'END {print NR + 0}') || tracked=0
                if [ "${tracked:-0}" -gt 0 ]; then
                    paths="${paths}${body}
"
                    continue
                fi
                echo "  note: a derived-tree-paths declaration names '${body}', which nothing tracks" >&2
                refused=1
                continue
                ;;
            esac
            ;;
        esac
        echo "  note: a derived-tree-paths declaration names '${body}', which is not one repository-relative subtree" >&2
        refused=1
    done <<EOF
$decl
EOF
    # ---- a declaration the reader never opens (B4.5) -------------------------
    # One sweep of the whole TRACKED tree for the opening sentinel — the same
    # population the secret scan reads — and a note for every hit in a file the
    # loop above did not scan. `git grep` answers 1 when nothing matches, which
    # is the ordinary case on this tree and is not a failure.
    stray=$(git -C "$dir" grep -I -l -F -e "$GATE_TREE_DECL_BEGIN" 2>/dev/null) || stray=""
    while IFS= read -r sf; do
        [ -n "$sf" ] || continue
        inside=0
        case "$scanned" in
        *" $sf "*) inside=1 ;;
        esac
        [ "$inside" = 0 ] || continue
        # ON A COMMENT LINE, exactly as the reader requires — so a drive that
        # WRITES the sentinel (inside an `echo`, into a scratch checkout) is not
        # reported as having declared anything.
        hits=$(awk -v b="$GATE_TREE_DECL_BEGIN" '
            {
                lead = $0
                sub(/^[ \t]*/, "", lead)
                if ((substr(lead, 1, 1) == "#" || substr(lead, 1, 1) == "*") && index($0, b)) print FNR
            }
        ' "$dir/$sf" 2>/dev/null) || hits=""
        [ -n "$hits" ] || continue
        echo "  note: declaration at ${sf} is not in a source the reader scans — nothing excluded" >&2
    done <<EOF
$stray
EOF
    if [ "$refused" = 1 ]; then
        echo "  note: so NOTHING is excluded — the verdict key measures the WHOLE tree, which" >&2
        echo "        costs a re-measure and is never a hit on an exclusion nobody could verify." >&2
        return 1
    fi
    [ -n "$paths" ] || return 0
    printf '%s' "$paths" | LC_ALL=C sort -u
}

# ---- THE ONE SUBTRACTION SITE -----------------------------------------------
#
# TWO READERS, ONE ARITHMETIC. `gate_measured_tree` asks the question of the
# WORKING tree and `gate_measured_tree_of` asks it of a REF, and the day those
# two subtract differently is the day a bank and a consult are about different
# bytes while both call themselves "the measured tree". That is not a
# hypothetical: it is this very defect with the fix applied badly — the
# consumer's own first attempt copied the helper, and two keys computed two
# ways is the defect again with a longer fuse. So the subtraction lives exactly
# here, both readers hand it an index, and a census of the one cached-removal
# command below counts exactly one occurrence of it in this file — the count
# IS the assertion, and it is made by
# `test_loop_ledger.sh::case_one_subtraction_site_serves_both_measured_tree_readers`,
# which reds the moment a second copy appears. The literal is deliberately not
# spelled in this paragraph: a prose mention would be counted like code and
# would break the census it is describing.
#
# gate__subtract_and_write <index-file> — the declared derived paths removed
# from that index, and the resulting tree on stdout. Exit 1 if nothing could be
# written. The index is the caller's to make and the caller's to remove.
gate__subtract_and_write() {
    local idx="$1" root paths p tree
    # `--cached` never touches the working tree — a declared artefact stays on
    # disk, tracked, committed and reviewed; only this throwaway index forgets
    # it. `-f` because a declared path is by definition one whose disk bytes
    # differ from HEAD, which is exactly what `git rm --cached` refuses without
    # it. A refusal from the reader leaves `paths` empty and excludes nothing.
    root=$(git rev-parse --show-toplevel 2>/dev/null) || root=.
    paths=$(gate__derived_tree_paths "$root") || paths=""
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        GIT_INDEX_FILE="$idx" git -C "$root" rm -r -f --cached -q --ignore-unmatch -- "$p" \
            >/dev/null 2>&1 || true
    done <<EOF
$paths
EOF
    tree=$(GIT_INDEX_FILE="$idx" git write-tree 2>/dev/null)
    [ -n "$tree" ] || return 1
    printf '%s\n' "$tree"
}

# The content address of the working state. GIT_INDEX_FILE points `git add` at
# a scratch index, so the real index is untouched; `git add -A` honours
# .gitignore, which makes the key "the content the gate can read" rather than
# "the content plus every build artefact" — minus the paths a leg DECLARES it
# derives, which makes it "the content the gate can read AND something it
# measures reads back".
gate_measured_tree() {
    local idx tree
    idx=$(mktemp "${TMPDIR:-/tmp}/djb-gate-index.XXXXXX") || return 1
    rm -f "$idx" # git wants to create it, not inherit an empty one
    if ! GIT_INDEX_FILE="$idx" git read-tree HEAD >/dev/null 2>&1; then
        rm -f "$idx"
        return 1
    fi
    if ! GIT_INDEX_FILE="$idx" git add -A >/dev/null 2>&1; then
        rm -f "$idx"
        return 1
    fi
    tree=$(gate__subtract_and_write "$idx") || tree=""
    rm -f "$idx"
    [ -n "$tree" ] || return 1
    printf '%s\n' "$tree"
}

# gate_measured_tree_of <tree-ish> — THE SAME KEY, ASKED OF A REF.
#
# WHY IT HAD TO EXIST. Everything that decides whether a tree has been measured
# — the pre-push wall's consult and its identity compare, the docs-only road's
# ancestor walk and its delta — was reading a ref RAW (`<sha>^{tree}`) and then
# holding that answer up against `gate_measured_tree`, which is the same tree
# with every declared derived path SUBTRACTED. On this template nothing is
# declared, the two readings are the same forty characters, and the
# disagreement was invisible for as long as the mechanism has existed. On a
# product that declares one they can never agree, and the consequence is total:
# every push is refused as "not the tree in this checkout" — the checkout's own
# tree, mistaken for a foreign one, by arithmetic, on every push forever.
#
# NO `git add -A` HERE, and that is the whole difference. A ref HAS no working
# tree: the answer is the committed bytes minus the declarations, which on a
# clean checkout is exactly what `gate_measured_tree` answers, and the equality
# of those two is what the wall's compare and the road's `measured != tree`
# guard both rest on. On a dirty checkout they differ — which is the guard
# working, not a defect.
#
# THE DECLARATION LIST IS THIS CHECKOUT'S, NOT THE REF'S (declared blind spot).
# The subtraction reads the derivers on disk, so a ref that declared a
# different set is measured with today's set. Every caller here is asking about
# a ref in its own line of development, where the two are the same in practice;
# a ref whose declarations genuinely differ would be measured slightly wrong,
# and the belt is that a wrong key is a MISS — a re-measure — and never a false
# hit on a tree nobody looked at.
gate_measured_tree_of() {
    local rev="${1:-HEAD}" idx tree
    idx=$(mktemp "${TMPDIR:-/tmp}/djb-gate-index.XXXXXX") || return 1
    rm -f "$idx"
    if ! GIT_INDEX_FILE="$idx" git read-tree "$rev" >/dev/null 2>&1; then
        rm -f "$idx"
        return 1
    fi
    tree=$(gate__subtract_and_write "$idx") || tree=""
    rm -f "$idx"
    [ -n "$tree" ] || return 1
    printf '%s\n' "$tree"
}

# ---- what sanctioned the run -------------------------------------------
#
# THE SECOND HALF OF "WHO ASKED", and the half that turns a measurement into an
# audit. `caller=` says which of four kinds a run was. It cannot say WHY a
# `quality-rung` full gate was run, and once `scripts/check.sh` began REFUSING
# unsanctioned full runs, the reason stopped being optional: every full gate now
# arrives with one, and a reason that is not written down is a reason that
# existed for the length of one terminal session.
#
# So the sanction rides into the verdict row beside the caller. It is free text
# by construction — `<rung-id>: <reason>` is a shape, not a vocabulary, and
# whether the reason was a good one is a PM's read rather than a check. It goes
# LAST on the line, after `caller=`, for two reasons: it is the only field that
# can contain spaces, and appending keeps every pre-existing line parsing
# exactly as it did (`gate_ledger_lookup` matches `" <tree> full "` and `^v1 `;
# `gate_run_lookup` reads field 4). The schema tag stays `v1` because nothing
# that could already parse a line stopped being able to.
#
#: Set by `scripts/check.sh` before it records: one phrase naming what made this
#: full run legal. Empty means nothing said, which is what every line written
#: before the valve existed says.
GATE_RUN_SANCTION=""

# ---- what the run COST, recorded beside what it judged ------------------
#
# A VERDICT ROW SAID WHAT WAS MEASURED AND NEVER WHAT IT COST. "The gate is
# slow" and "the gate spent nine minutes queued behind somebody else's push"
# are different complaints with different answers, and neither was answerable
# from the ledger: the wait was announced to a terminal that scrolled away, and
# the suite's wall time was printed by the leg and then thrown away. Two fields
# turn every banked row into a datum — how long this run QUEUED, and how long
# the pytest leg actually TOOK — so the population is readable afterwards
# instead of re-argued from memory.
#
# THEY ARE APPENDED, and that is the precedent `sanction=` set one field over
# and `passes=`/`tree=`/`env=` set on the loop row: every line written before
# these fields existed parses exactly as it did, is still a legal hit, and the
# schema tag does not move, because nothing that could already read a row
# stopped being able to.
#
# `sanction=` IS THEREFORE NO LONGER LAST, and its "only field that can contain
# spaces" comment above becomes a rule for READERS rather than a fact about the
# line: a reader taking the sanction must take it by name and stop at the two
# trailing `name=value` fields. Nothing in this tree reads it that way today —
# it is asserted as a substring, in `test_gate_lease.sh`'s sanction case — and
# this sentence is here so the next reader who writes such a parser is told.
#
# THE VALUES COME FROM GLOBALS THE OTHER TWO LIBRARIES SET, never from
# parameters: `GATE_LEASE_WAITED` and `GATE_SLOT_WAITED` are
# `scripts/gate_lease.sh`'s (each acquire call sets its own, and a mode that
# takes neither leaves both at 0, which is the honest answer), and
# `GATE_PYTEST_TOOK` is `scripts/check.sh`'s, set by `leg`/`leg_done` when the
# leg that just finished was a pytest leg. An absent global is 0, which reads as
# "this run did not wait" / "this run started no suite" — both true of every
# caller that has no pytest leg at all.
gate_ledger_cost_fields() {
    printf ' waited=%s took=%s' \
        "$((${GATE_LEASE_WAITED:-0} + ${GATE_SLOT_WAITED:-0}))" \
        "${GATE_PYTEST_TOOK:-0}"
}

# ---- the LEAK PROOF the row stood on -----------------------------------
#
# WHY A ROW NOW NAMES A BOX. `scripts/check.sh`'s `pytest-x2` unit runs the
# suite TWICE under one seed, and the second pass is the LEAK proof: a test
# that passes alone and fails behind its own leftovers reds there and nowhere
# else. Under `pm_push.sh --bank --on-boxes N` that belt costs a whole pass of
# box-time on every shard — and it is a WITHIN-SHARD proof, which
# `docs/product/build-contract.md` § SHARDED declares as a narrowing — while a
# whole-suite two-pass run under one seed already executes on the acceptance
# box and was composed nowhere. The bank was paying for the stronger proof and
# banking the weaker one. So since ADR gate-1's 2026-09-18 amendment the shards
# run ONE pass, the acceptance box's two passes ARE the proof, and the row
# carries which box proved it and with what status.
#
# IT IS APPENDED AND IT IS LAST, which is the precedent `sanction=` set and
# `waited=`/`took=` set after it: every line written before this field existed
# parses exactly as it did, is still a legal hit, and `GATE_LEDGER_SCHEMA` does
# not move, because nothing that could already read a row stopped being able to.
# THE READER'S RULE ONE SECTION UP THEREFORE COUNTS THREE: a reader taking
# `sanction=` by name must stop at the THREE trailing `name=value` fields, not
# the two that sentence named when it was written.
#
# A MALFORMED VALUE IS A REFUSAL AND NOT A ROW, and this field is the only one
# here that works that way. Everything else degrades to an honest "this run did
# not wait" or "nothing said"; this one cannot, because it is the one field a
# READER acts on — `gate_ledger_lookup` honours a one-pass leg only when this
# field is present and green, so a value it could not parse would read as "no
# proof" and the writer would have silently banked a weaker claim than the run
# meant. A row nothing can parse is worse than a row that says nothing.
#
#: Set by `scripts/pm_push.sh` beside `GATE_RUN_SANCTION` when a bank ran its
#: pytest shards at one pass: `acceptance:<box-id> rc=<n>` — the box that ran
#: the whole-suite two-pass proof, and the status it exited. EMPTY means no
#: field at all, which is what every row written before this existed says, and
#: what every two-pass run goes on saying.
GATE_RUN_LEAK_PROOF=""

# gate_ledger_proof_field → the field on stdout (leading space), or nothing.
# Exit 1 when the global is set and will not parse — a note on stderr, no
# field on stdout, and `gate_ledger_record` turns that into no row.
gate_ledger_proof_field() {
    # THE WRITER'S GRAMMAR IS THE READER'S, NOT A SUPERSET OF IT. `rc=` takes a
    # decimal with no leading zero, because the reader honours exactly `rc=0`:
    # a writer that accepted `rc=00` would bank a row whose green the reader
    # then read as red, and the two would disagree about a row neither had any
    # way to flag. One grammar, refused at the only end that can still fix it.
    local proof re='^acceptance:[A-Za-z0-9-]+ (rc=0|rc=[1-9][0-9]*)$'
    # Newlines would make one row into two — stripped here exactly as the
    # sanction's are, and in the same place, for the same reason.
    proof=$(printf '%s' "${GATE_RUN_LEAK_PROOF:-}" | tr '\n' ' ')
    # Stripping leaves whitespace at the ends of a value that carried a
    # trailing newline. The grammar is judged on the TRIMMED value and the
    # trimmed value is what gets written, so the two can never disagree.
    proof=${proof#"${proof%%[![:space:]]*}"}
    proof=${proof%"${proof##*[![:space:]]}"}
    [ -n "$proof" ] || return 0
    if [[ ! $proof =~ $re ]]; then
        echo "note: GATE_RUN_LEAK_PROOF is set and will not parse, so NO ROW was written." >&2
        echo "  The grammar is 'acceptance:<box-id> rc=<n>' — the box that ran the" >&2
        echo "  whole-suite two-pass leak proof, and the status it exited. A row" >&2
        echo "  carrying a leak-proof field nothing can read would be honoured as a row" >&2
        echo "  carrying none, which is a weaker claim than the run meant to bank." >&2
        echo "  Got: leak-proof=${proof}" >&2
        return 1
    fi
    printf ' leak-proof=%s' "$proof"
}

# gate_ledger_record <tree> <legs-csv> — one line, appended, schema first.
gate_ledger_record() {
    local tree=$1 legs=$2 path sanction proof
    path=$(gate_ledger_path) || return 1
    # Newlines would make one row into two, and a row nothing can parse is worse
    # than a row that says nothing. check.sh's shape check already refuses them
    # at the door; this is the ledger refusing to be the place it matters.
    sanction=$(printf '%s' "${GATE_RUN_SANCTION:-}" | tr '\n' ' ')
    # THE PROOF IS RESOLVED BEFORE A BYTE IS WRITTEN, and its refusal is the
    # whole row's. Dropping just the field would bank a row that reads as
    # "two passes, nothing to prove" — see the field's own argument above.
    proof=$(gate_ledger_proof_field) || return 1
    if [ -n "$sanction" ]; then
        printf '%s %s full %s %s caller=%s sanction=%s%s%s\n' \
            "$GATE_LEDGER_SCHEMA" "$tree" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$legs" \
            "$(gate_caller)" "$sanction" "$(gate_ledger_cost_fields)" "$proof" >>"$path"
    else
        printf '%s %s full %s %s caller=%s%s%s\n' \
            "$GATE_LEDGER_SCHEMA" "$tree" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$legs" \
            "$(gate_caller)" "$(gate_ledger_cost_fields)" "$proof" >>"$path"
    fi
}

# gate_full_legs — the member set a FULL run covers, on stdout, comma-joined.
# EMPTY when this directory has no gate to read one from — which is a checkout
# with no `scripts/check.sh`, not a broken read: a place with no gate makes no
# claim about a leg set.
#
# TWO READERS, AND THE PRODUCT-LEG DRAWER IS WHAT CHOOSES BETWEEN THEM.
#
#   NO DRAWER — `check.sh`'s own `FULL_LEGS=` assignment, exactly as this
#   function has always read it. On such a tree the assignment IS the leg set:
#   the listing would add only the drives the selftest leg walks, which a full
#   run does walk and which the row already covers either way, and reading it
#   would mean running the gate as a subprocess from the pre-push hook's
#   consult — whose whole point is that honouring a banked row costs a lookup
#   and not a gate. So the answer, the row and the cost are byte-identical to
#   the tree that had never heard of a drawer.
#
#   A DRAWER — `./scripts/check.sh --list-legs`, column 4 flattened. For that
#   tree the assignment is WRONG: a product declares its own legs in
#   `scripts/local/legs/` and `check.sh` grows `FULL_LEGS` at runtime with one
#   `local:<name>` per declared leg, so a reader of the text would bank and
#   compare a set that silently omitted every one of them — the row would
#   vouch for legs the bank never named. The listing is the gate saying what
#   its units are made of, it is what `pm_push.sh --bank --on-boxes` plans
#   from, and it is the one answer both sides of the wall then read.
#
# THE DRAWER ANSWER IS A SUPERSET OF THE ANNOUNCED LEGS, deliberately: a unit
# that shards by a registered population names that population in its
# `composed-of`, so the selftest drives are members there too. A full run walks
# every one of them, so the row is a stronger and truer claim; and
# `gate_ledger_lookup` compares by COVER, with both sides built by this one
# function, so they cannot drift apart.

#: Memoised for the process. The listing costs a whole shell startup of
#: `check.sh`, and the pre-push hook asks this question once per pushed tree.
GATE_FULL_LEGS_MEMO=""
gate_full_legs() {
    local listing rc=0 drawer f tmp
    [ -n "$GATE_FULL_LEGS_MEMO" ] && {
        printf '%s' "$GATE_FULL_LEGS_MEMO"
        return 0
    }
    [ -r scripts/check.sh ] || return 0
    # THE DRAWER DECIDES WHICH READER ANSWERS, AND THAT IS THE WHOLE OF IT.
    # A tree with no product leg in `scripts/local/legs/` has a leg set that IS
    # the assignment — the listing would add only the drives the selftest leg
    # walks, and every one of them is already covered by the row the gate
    # writes — so the text is read, the answer is byte-identical to what it has
    # always been, and NO SUBPROCESS RUNS. That last clause is not tidiness:
    # this function is on the pre-push hook's consult path, whose whole point
    # is that honouring a banked row costs a lookup and not a gate.
    #
    # A tree WITH a drawer pays the listing, because for that tree the text is
    # wrong: `check.sh` grows `FULL_LEGS` at runtime with one `local:<name>`
    # per declared leg, and a reader of the assignment would bank and compare a
    # set that silently omitted every product leg — the row would vouch for
    # legs the bank never named. The product pays for its own feature.
    drawer="${DJB_LOCAL_LEGS_DIR:-scripts/local/legs}"
    if [ -d "$drawer" ]; then
        for f in "$drawer"/*.sh; do
            [ -f "$f" ] || continue
            case "${f##*/}" in _*) continue ;; esac
            rc=0
            # IN PROCESS WHEN THE GATE IS THE CALLER, A SUBPROCESS OTHERWISE —
            # one listing, two doors to it. `check.sh` sources this file and
            # defines `gate_list_legs` below its own unit table, so by the time
            # the gate banks a row the function is here and the answer costs
            # nothing; the pre-push hook and `pm_push.sh` source this file
            # ALONE, and for them the listing is what the gate prints.
            if command -v gate_list_legs >/dev/null 2>&1; then
                listing=$(gate_list_legs 2>/dev/null) || rc=$?
            else
                # REDIRECTED TO A FILE AND READ BACK, NEVER CAPTURED. A command
                # substitution IS a pipe and the gate refuses one outright
                # (exit 2, "run it bare or redirect to a file") — which is why
                # this is four lines rather than one, and why `pm_push.sh` and
                # `ci.yml` spell it the same way.
                tmp=$(mktemp "${TMPDIR:-/tmp}/djb-gate-legs.XXXXXX") || break
                ./scripts/check.sh --list-legs >"$tmp" 2>/dev/null || rc=$?
                listing=$(cat "$tmp")
                rm -f "$tmp"
            fi
            if [ "$rc" = "0" ] && [ -n "$listing" ]; then
                GATE_FULL_LEGS_MEMO=$(printf '%s\n' "$listing" |
                    awk -F'\t' 'NF >= 4 { print $4 }' | tr ',' '\n' |
                    awk 'NF && !($0 in seen) { seen[$0] = 1; printf "%s%s", (n++ ? "," : ""), $0 } END { print "" }')
            fi
            break
        done
    fi
    if [ -z "$GATE_FULL_LEGS_MEMO" ]; then
        # NO DRAWER, OR A LISTING THIS READER COULD NOT SPLIT INTO FOUR COLUMNS
        # — a stub gate, an older one, a table that has lost its subject. Both
        # land here rather than on an empty answer, and the difference is
        # fail-closed against fail-open: an empty answer switches the leg
        # comparison OFF and honours every row whatever it names.
        #
        # READ WHOLE, THEN SLICE. `sed` reads its input to the end, so it never
        # closes the pipe under its producer; the first match is taken from the
        # captured text rather than by an early-exiting reader.
        listing=$(sed -n 's/^FULL_LEGS=//p' scripts/check.sh) || return 0
        GATE_FULL_LEGS_MEMO="${listing%%$'\n'*}"
    fi
    printf '%s' "$GATE_FULL_LEGS_MEMO"
}

# gate_ledger_lookup <tree> → most recent matching line on stdout, exit 0;
# exit 1 when the tree has no verdict.
#
# THE LEGS FIELD IS COMPARED, AND UNTIL R3's F3x IT WAS NOT. A row said
# which legs ran and nothing ever read it, so a row naming a SHORTER set than a
# full run announces was honoured exactly as a complete one. That was not
# unsound on this tree — `scripts/check.sh` is inside the measured tree, so a
# leg-set change moves the key, and `--leg <unit>` banks nothing at all by
# design — which is why the finding was graded legibility. But a field nobody
# reads is a field that means whatever the next writer decides, and the belt is
# two lines: the row's set must COVER the set this gate declares.
#
# THE BUILDER'S CHOICE, STATED, because the criterion offered two. The other was
# to drop field 5 and bump `GATE_LEDGER_SCHEMA`, and it was rejected on cost: a
# schema bump invalidates every banked full verdict in every checkout on the
# machine — an eight-minute re-measure each — to buy a legibility fix, and it
# throws away the one thing a row says about WHAT it measured. Comparing keeps
# the audit value, needs no bump, and turns the unread field into a checked one.
#
# A SUPERSET HITS. More legs than this gate asks for is a stronger claim, not a
# weaker one, and refusing it would make every leg added to the gate invalidate
# rows that genuinely covered it.
#
# AND WHERE THERE IS NO `scripts/check.sh` THERE IS NO COMPARISON — declared
# here rather than discovered. The leg set is a property of the gate in this
# checkout; a directory with no gate declares none, so there is nothing to
# compare against and the lookup is what it always was. The tree hash is still
# the key, and it is still the thing doing the work.
#
# AND THE MEMBER GRAMMAR IS NOW `<leg>[/<passes>]`, which is the one
# change to the rule above. A sharded bank runs `pytest-x2` at ONE pass and
# names the member `pytest-x2/1`; the whole-suite two-pass leak proof it stood
# on ran on the acceptance box and rides in the row's `leak-proof=` field. So a
# required leg is covered when a member IS the leg name (as it always was), or
# when it is `pytest-x2/1` AND the row carries a GREEN proof, or when it is
# `<leg>/<n>` for a DECIMAL n of two or more — a pass count at or above the
# default is the claim the bare name always made. `pytest-x2/1` with no field,
# with a red `rc=`, or with a field that will not parse is NOT covered, and the
# note says which of those it was rather than repeating the generic missing-leg
# line: a reader who cannot tell "the row is short" from "the row ran half of
# what it says" re-measures for a reason they cannot act on.
#
# THE SUFFIX IS A DECIMAL AND THE PATTERN SAYS SO. A `<leg>/*` glob honours
# `<leg>/0`, `<leg>/`, `<leg>/x` and `<leg>/1/1` — three of which claim LESS
# than one pass and the fourth of which is not a pass count at all — while the
# sentence above promises "at or above the default". A cover rule whose glob is
# wider than its prose is a green with no argument behind it, so the two
# alternatives below spell the decimal: `[2-9]…` and `[1-9][0-9]…`. Anything
# else falls through to the generic missing-leg refusal, which is the honest
# answer to a member this reader cannot interpret.
#
# AND ONE PASS IS SANCTIONED FOR ONE UNIT, BY NAME. ADR gate-1's 2026-09-18
# amendment bends the two-pass rule for the SHARDED PYTEST UNIT and for nothing
# else: the acceptance box's proof is a whole-suite two-pass pytest run, so it
# vouches for `pytest-x2` and has nothing to say about `selftest`, `fe` or any
# other leg. A generic `<leg>/1 + green proof` rule would let one leg's proof
# buy another leg's second pass, which is the exact shape of claim this ledger
# exists to refuse. So the unit is named here, and a second two-pass unit means
# editing this name rather than inheriting the exemption by accident.
#
# A PROOF NOBODY NEEDED IS PRINTED, never silently honoured and never silently
# refused. A row whose members are all full-pass carries no one-pass claim for
# the field to support, so the field is ignored — and ignoring a field without
# saying so is how the next reader learns it is load-bearing when it is not.
gate_ledger_lookup() {
    local tree=$1 path line required leg rowlegs
    local proof member covered onepass unsanctioned proofgreen proofused
    local proofre='^acceptance:[A-Za-z0-9-]+ rc=0$'
    # The one unit ADR gate-1's amendment lets run a single pass, named rather
    # than pattern-matched: the proof is a pytest run and vouches for pytest.
    local onepass_unit=pytest-x2
    path=$(gate_ledger_path) || return 1
    [ -f "$path" ] || return 1
    line=$(grep -F " $tree full " "$path" | grep "^$GATE_LEDGER_SCHEMA " | tail -1)
    [ -n "$line" ] || return 1
    required=$(gate_full_legs)
    if [ -n "$required" ]; then
        # Field 5 of the row, positionally — `<schema> <tree> full <date> <legs>`.
        rowlegs=$(printf '%s\n' "$line" | awk '{print $5}')
        # The proof is the row's LAST field, and it is taken from the right
        # (`##`, longest prefix) so that a `sanction=` phrase which happens to
        # contain the word cannot be mistaken for the field itself.
        case "$line" in
        *" leak-proof="*) proof=${line##*" leak-proof="} ;;
        *) proof="" ;;
        esac
        proofgreen=0
        if [[ $proof =~ $proofre ]]; then
            proofgreen=1
        fi
        proofused=0
        for leg in $(printf '%s' "$required" | tr ',' ' '); do
            covered=0
            onepass=0
            unsanctioned=0
            for member in $(printf '%s' "$rowlegs" | tr ',' ' '); do
                case "$member" in
                "$leg")
                    covered=1
                    break
                    ;;
                "${leg}/1")
                    if [ "$leg" = "$onepass_unit" ]; then
                        onepass=1
                        if [ "$proofgreen" -eq 1 ]; then
                            covered=1
                            proofused=1
                        fi
                    else
                        unsanctioned=1
                    fi
                    break
                    ;;
                "${leg}/"[2-9]* | "${leg}/"[1-9][0-9]*)
                    covered=1
                    break
                    ;;
                esac
            done
            if [ "$covered" -eq 1 ]; then
                continue
            fi
            echo "note: a banked row for this tree names legs that do not cover this gate's" >&2
            if [ "$onepass" -eq 1 ]; then
                echo "  declared set — missing '${leg}' — the row ran ONE pass and carries no green leak proof (leak-proof=${proof:-none})." >&2
                echo "  The second pass is the leak proof; on a sharded bank it runs on the" >&2
                echo "  acceptance box and the row names it. Not honoured — measuring." >&2
            elif [ "$unsanctioned" -eq 1 ]; then
                echo "  declared set — missing '${leg}' — the row ran ONE pass of a leg that is not '${onepass_unit}', and one pass is sanctioned for that unit alone (leak-proof=${proof:-none})." >&2
                echo "  The acceptance box's proof is a whole-suite two-pass pytest run; it" >&2
                echo "  vouches for pytest and for nothing else. Not honoured — measuring." >&2
            else
                echo "  declared set (missing '${leg}'), so it is not honoured — measuring." >&2
            fi
            return 1
        done
        if [ -n "$proof" ] && [ "$proofused" -eq 0 ]; then
            echo "note: leak-proof ignored: the row ran two passes over every leg this gate" >&2
            echo "  declares, so nothing in it rested on the proof (leak-proof=${proof})." >&2
        fi
    fi
    printf '%s\n' "$line"
}

# gate_has_green <tree> → exit 0 iff a full green run measured this tree.
gate_has_green() { gate_ledger_lookup "$1" >/dev/null; }

# ---- the DOCS-ONLY push path ------------------------------------------------
#
# WHAT IT IS. The doctrine is one full gate per push and the verdict is keyed on
# the TREE, so a ledger, readouts, queue or ADR-signature commit — bytes no leg
# of the gate executes — moves the key and costs a whole bank. The v2.1 tail
# paid three sequential banks (CLOSE, RELEASE, close-up) whose MEASURED surface
# never moved, and BOXBANK-16 paid 28 minutes for eight of them. This says when
# `pm_push.sh --bank` may run the readers those bytes actually have — seconds on
# this Mac — and write an ORDINARY full row for the tree it is about to push.
#
# IT IS NOT A NEW KIND OF ROW, AND THAT IS THE DESIGN (the criterion's rejected
# alternative (i)). The row `gate_ledger_record` writes here is the same row a
# bank writes: same schema, same legs field, same `leak-proof=`, keyed on the
# tree that is about to be PUSHED. The pre-push hook honours it unedited and
# `gate_ledger_lookup` needs no new clause. What is different is the SANCTION —
# `docs-only from=<M> paths=<n> readers=<csv>` — which is free text by
# construction and is therefore the honest place for a claim that is a PM's to
# read rather than a reader's to act on.
#
# THE FOUR DECLARATIONS (principle 10), stated where the code is:
#   SOURCE OF TRUTH — the nearest ANCESTOR tree carrying an HONOURED full row,
#     followed through `from=` so the source is always a tree a gate MEASURED
#     rather than a tree that inherited. A reuse chain therefore never drifts:
#     R2 is diffed against M, never against R1.
#   KEY SEMANTICS — unchanged. The key is still the measured tree. This narrows
#     the WORK a push of that tree costs, never the claim the row makes.
#   INVALIDATION — any changed path outside the declared list; any path READ
#     literally by a module under `apps/` or `config/`; a source row that is not
#     honoured; a reader that exits non-zero. Every one of them is a full bank
#     and every one of them SAYS SO.
#   FAILURE BEHAVIOUR — fail closed, and never silent. A refusal names its cause
#     and ends in "full bank"; a reader that could not look is a full bank and
#     not a verdict. There is no silent admission anywhere on this path.
#
# WHAT IT DELIBERATELY DOES NOT DO: it does not take the delta out of the tree
# hash (rejected alternative (i) — the verdict must name the tree pushed), it
# does not read a commit SUBJECT (a `[docs-only]` subject is a claim, not a
# measurement), and it does not reuse per-leg inside a full bank (that shape
# still launches five boxes and still pays selftest's wall).

#: THE DECLARED LIST, RATIFIED, AND IT IS THE RULE'S WHOLE TEXT. `docs/**` (no
#: leg imports them), `README.md`, `CLAUDE.md`, `.claude/skills/**` (one drive
#: and one `rules.yaml` `doc:` entry read them — the reader derivation below
#: finds both), and `scripts/test_impact.json` (the bank's own output for the
#: banked tree; only drives name it).
#:
#: `CHANGELOG.md` AND `TEMPLATE_VERSION` ARE OUT, AND THEY ARE OUT BY
#: MEASUREMENT: pytest reads both (`apps/core/tests/test_settings.py`,
#: `apps/core/views.py`, `quality/partition.yaml`), so a release still pays one
#: bank. Widening this list is a ratified change and not a judgment call.
GATE_DOCS_ONLY_PATHS='docs/** README.md CLAUDE.md .claude/skills/** scripts/test_impact.json'

#: How far back the source walk looks along main's own first-parent line. A
#: bound rather than the whole history: the population this exists for is the
#: last handful of pushes, and an unbounded walk over a ledger of 300 kB is a
#: cost nobody asked for. Exhausting it is a refusal that says so.
GATE_DOCS_ONLY_DEPTH=${GATE_DOCS_ONLY_DEPTH:-60}

#: The plan `gate_docs_only_plan` leaves behind. Empty until it has run, and
#: empty is honest rather than stale — `LOOP_REUSE_TREE`'s contract, one
#: mechanism over. They are globals and the function is therefore CALLED
#: PLAINLY, never in `$(...)`: a substitution's copy of a global dies with the
#: subshell that set it.
GATE_DOCS_ONLY_SOURCE=""  # M — the measured tree the row rests on
GATE_DOCS_ONLY_LEGS=""    # the source row's legs field, copied verbatim
GATE_DOCS_ONLY_PROOF=""   # the source row's leak-proof value, or empty
GATE_DOCS_ONLY_N=""       # how many paths changed since M
GATE_DOCS_ONLY_READERS="" # the derived readers, comma separated
GATE_DOCS_ONLY_WHY=""     # the refusal, ending in "full bank"

# gate_docs_only_admits <path> → 0 when the path is on the declared list.
# ONE FUNCTION READS THE LIST, so "what is a docs-only path" has one answer.
gate_docs_only_admits() {
    local p=$1 pat noglob=0
    # THE LIST IS PATTERNS AND THE SHELL WOULD EXPAND THEM. `docs/**` in an
    # unquoted `for` is pathname expansion, and it QUIETLY becomes the
    # directories that happen to exist — so the declared list would mean
    # something different in every checkout, and `docs/product/queue.md` was
    # refused by the first draft of this function for exactly that reason.
    case $- in
    *f*) noglob=1 ;;
    esac
    set -f
    for pat in $GATE_DOCS_ONLY_PATHS; do
        case "$pat" in
        *'/**')
            case "$p" in
            "${pat%'**'}"*)
                [ "$noglob" = 1 ] || set +f
                return 0
                ;;
            esac
            ;;
        *)
            if [ "$p" = "$pat" ]; then
                [ "$noglob" = 1 ] || set +f
                return 0
            fi
            ;;
        esac
    done
    [ "$noglob" = 1 ] || set +f
    return 1
}

# gate_docs_only_row_field <row> <name> → the value of `<name>=` on the row.
# AN EOF READER, `drive_row_parts`'s shape and for its reason: no pipe whose
# exit status anything branches on.
gate_docs_only_row_field() {
    awk -v k="$2" '
        { for (i = 1; i <= NF; i++) if (index($i, k "=") == 1) v = substr($i, length(k) + 2) }
        END { if (v != "") print v }
    ' <<EOF
$1
EOF
}

# gate_docs_only_source <head-commit> → M on stdout; GATE_DOCS_ONLY_SOURCE,
# _LEGS and _PROOF set. Exit 1 with GATE_DOCS_ONLY_WHY set.
#
# THE WALK IS FIRST-PARENT AND IT SKIPS HEAD. First-parent because the line a
# bank is taken on is main's own and a walk into a merged branch's history would
# be asking about trees nobody pushed; skipping HEAD because a source is by
# definition something to diff AGAINST.
#
# THE NEAREST BANKED ANCESTOR IS THE ONLY CANDIDATE. When its row exists and is
# NOT honoured — a short legs field, a `pytest-x2/1` with no green proof — this
# refuses instead of walking past it to an older row. Walking past would be a
# reuse that stepped over the most recent thing the gate said about this line of
# development, which is precisely the row a reader would expect it to rest on.
#
# THE ROW IS READ THROUGH `gate_ledger_lookup` AND NOTHING ELSE (rule 13, one
# reader). "A row exists here but is not honoured" is therefore read off the
# lookup's own NOTE, which is the only signal it has for that state: exit 1 with
# nothing on stderr is "no row for this tree", exit 1 with a note is "a row, and
# here is why it does not stand". A second grep of the ledger file would be a
# second reader, and the day the two disagree is the day a reuse rests on a row
# the lookup never approved.
gate_docs_only_source() {
    local head=$1 depth=0 c tree row note from hops
    GATE_DOCS_ONLY_SOURCE=""
    GATE_DOCS_ONLY_LEGS=""
    GATE_DOCS_ONLY_PROOF=""
    while IFS= read -r c; do
        [ -n "$c" ] || continue
        depth=$((depth + 1))
        # THE MEASURED TREE OF THE ANCESTOR, because that is the only key a
        # full gate ever banks. Read raw, this lookup asks the ledger
        # for a tree no row is keyed on the moment a product declares a
        # derived path — so the walk finds nothing, the road refuses, and a
        # documentation push costs a full bank forever.
        tree=$(gate_measured_tree_of "${c}^{tree}" 2>/dev/null) || continue
        row=$(gate_ledger_lookup "$tree" 2>/dev/null) || row=""
        if [ -z "$row" ]; then
            note=$(gate_ledger_lookup "$tree" 2>&1 >/dev/null) || true
            if [ -n "$note" ]; then
                GATE_DOCS_ONLY_WHY="docs-only? no — the nearest banked ancestor's row is not honoured — full bank"
                printf '%s\n' "$note" >&2
                return 1
            fi
            continue
        fi
        # A REUSE ROW NAMES THE MEASURED TREE IT RESTS ON, AND THAT IS THE
        # SOURCE. Following `from=` is what keeps a chain of docs-only pushes
        # diffed against the last MEASURED tree rather than against the last
        # INHERITED one: without it, R2 would be diffed against R1, and a forged
        # or mistaken R1 row would hand R2 a delta that never showed the
        # `apps/` path R1 really carried.
        hops=0
        while :; do
            from=$(gate_docs_only_row_field "$row" from)
            [ -n "$from" ] || break
            hops=$((hops + 1))
            case "$from" in
            *[!0-9a-f]* | "") from="" ;;
            esac
            if [ -z "$from" ] || [ "$hops" -gt 4 ]; then
                GATE_DOCS_ONLY_WHY="docs-only? no — the nearest banked ancestor's row names a source this reader cannot follow — full bank"
                return 1
            fi
            row=$(gate_ledger_lookup "$from" 2>/dev/null) || row=""
            if [ -z "$row" ]; then
                GATE_DOCS_ONLY_WHY="docs-only? no — the nearest banked ancestor's row names from=${from}, which carries no honoured row of its own — full bank"
                return 1
            fi
            tree="$from"
        done
        GATE_DOCS_ONLY_SOURCE="$tree"
        GATE_DOCS_ONLY_LEGS=$(printf '%s\n' "$row" | awk '{print $5}')
        case "$row" in
        *" leak-proof="*) GATE_DOCS_ONLY_PROOF=${row##*" leak-proof="} ;;
        *) GATE_DOCS_ONLY_PROOF="" ;;
        esac
        printf '%s\n' "$tree"
        return 0
    done <<EOF
$(git rev-list --first-parent --skip=1 --max-count="$GATE_DOCS_ONLY_DEPTH" "$head" 2>/dev/null)
EOF
    GATE_DOCS_ONLY_WHY="docs-only? no — no honoured full row on any of the last ${GATE_DOCS_ONLY_DEPTH} first-parent ancestors (walked ${depth}) — full bank"
    return 1
}

# gate_docs_only_literal_reads <needle>… → `<file>:<line> <needle>` per hit.
#
# WHAT A *LITERAL READ* IS, AND WHY THE DEFINITION IS NARROWER THAN "MENTIONS".
# The `--loop` reuse one mechanism over refuses on ANY mention of a docs path in
# `apps/`, and that was measured: it refuses `docs/product/queue.md` and
# `docs/product/architecture.md`, which are the two commits this path exists
# for. So the question asked here is not "is this path spelled" but "does
# anything OPEN it": a value in quotes (`"P"`, `'P'`, or the quoted basename) or
# a YAML `file:` value or list item. A backtick mention and a comment are prose
# — every one of the forty-odd hits in `apps/` today is one of those two — and
# prose is admitted.
#
# THE DIRECTION OF EVERY DOUBT IS STILL CLOSED. A quoted mention inside a
# docstring is judged a read; a path assembled from parts, reached by a glob or
# walked as a directory is judged prose and MISSED. That second half is this
# path's declared blind spot, and the belt is the next non-docs push.
gate_docs_only_literal_reads() {
    local roots="" r out n
    local -a args=()
    for r in apps config quality; do
        if [ -d "$r" ]; then
            roots="${roots}${roots:+ }${r}"
        fi
    done
    [ -n "$roots" ] || return 0
    for n in "$@"; do
        args+=(-e "$n")
    done
    [ "${#args[@]}" -gt 0 ] || return 0
    # `-I` because a binary that happens to contain the bytes is not a read, and
    # the judge below would see a line it cannot parse. A grep that matched
    # nothing exits 1, which is not an error here — it is the ordinary answer.
    # shellcheck disable=SC2086
    out=$(grep -rnI -F "${args[@]}" $roots 2>/dev/null) || out=""
    [ -n "$out" ] || return 0
    awk -v needles="$*" '
    BEGIN { nn = split(needles, NEEDLE, " "); sq = sprintf("%c", 39) }
    {
        i = index($0, ":"); if (i == 0) next
        file = substr($0, 1, i - 1); rest = substr($0, i + 1)
        j = index(rest, ":"); if (j == 0) next
        lno = substr(rest, 1, j - 1); text = substr(rest, j + 1)
        hash = index(text, "#")
        for (k = 1; k <= nn; k++) {
            needle = NEEDLE[k]
            L = length(needle); start = 1
            while (1) {
                p = index(substr(text, start), needle)
                if (p == 0) break
                at = start + p - 1
                start = at + 1
                a = at
                while (a > 1 && substr(text, a - 1, 1) ~ /[A-Za-z0-9_.\/-]/) a--
                b = at + L - 1
                while (b < length(text) && substr(text, b + 1, 1) ~ /[A-Za-z0-9_.\/-]/) b++
                # THE TOKEN, NOT THE SUBSTRING. `src/primitives/README.md` is
                # not a read of `README.md`, and a basename needle would say it
                # was.
                if (substr(text, a, b - a + 1) != needle) continue
                # After the first `#` on the line is a comment mention.
                if (hash > 0 && at > hash) continue
                before = (a > 1) ? substr(text, a - 1, 1) : ""
                after = (b < length(text)) ? substr(text, b + 1, 1) : ""
                if (before == "`") continue
                if (before == "\"" && after == "\"") { print file ":" lno " " needle; next }
                if (before == sq && after == sq) { print file ":" lno " " needle; next }
                lead = substr(text, 1, a - 1)
                if (lead ~ /file:[ \t]*$/) { print file ":" lno " " needle; next }
                if (lead ~ /^[ \t]*-[ \t]+$/) { print file ":" lno " " needle; next }
            }
        }
    }
    ' <<EOF
$out
EOF
}

# gate_docs_only_covers <declared> <path> → 0 when the declaration covers it.
gate_docs_only_covers() {
    local d=${1%/} p=$2
    if [ "$d" = "$p" ]; then
        return 0
    fi
    case "$p" in
    "$d"/*) return 0 ;;
    esac
    return 1
}

# gate_docs_only_drives <path>… → every drive whose declaration names one of
# these paths, or a directory prefix of one, on stdout.
#
# THE DECLARATION IS THE DRIVE'S OWN, read through `drive_marker_line` — the
# same line the selftest leg's reuse keys on, so a drive that declares what it
# reads is selected here for free and a drive that does not is missed here
# exactly as it is missed there. A `# cites:` line is NOT read: a citation is
# explicitly not a subject (see `drive_cites_line`), and selecting on one would
# re-drive a drive that never opens the file.
gate_docs_only_drives() {
    local f line tok p out="" noglob=0
    case $- in
    *f*) noglob=1 ;;
    esac
    for f in scripts/tests/test_*.sh; do
        [ -f "$f" ] || continue
        line=$(drive_marker_line "$f") || continue
        line=${line#*drives:}
        # A DECLARED TOKEN IS A PATH AND NEVER A GLOB HERE, for
        # `gate_docs_only_admits`'s reason: a declaration carrying a `*` would
        # otherwise be expanded against this checkout before it was compared.
        set -f
        for tok in $line; do
            for p in "$@"; do
                if gate_docs_only_covers "$tok" "$p"; then
                    out="${out}${f}
"
                    break 2
                fi
            done
        done
        [ "$noglob" = 1 ] || set +f
    done
    [ -n "$out" ] || return 0
    printf '%s' "$out" | LC_ALL=C sort -u
}

# gate_docs_only_plan <head-commit>
#   0  every changed path since M is on the declared list and the readers are
#      derived: GATE_DOCS_ONLY_SOURCE, _LEGS, _PROOF, _N and _READERS are set.
#   1  measure. GATE_DOCS_ONLY_WHY is the sentence, and it always ends in
#      "full bank".
#
# IT DERIVES AND DECIDES; IT RUNS NOTHING. The readers are RUN by the caller
# (`scripts/pm_push.sh`), which is the one place in this system that already
# runs the gate and answers its status.
gate_docs_only_plan() {
    local head=$1 tree delta p n=0 needles="" hit file engine=0 d readers measured
    GATE_DOCS_ONLY_N=""
    GATE_DOCS_ONLY_READERS=""
    GATE_DOCS_ONLY_WHY=""
    # MEASURED, NOT RAW — and the delta below is taken between two
    # measured trees, so a churn in a DECLARED derived path is subtracted from
    # both ends and never shows up as a changed path. That is the same
    # sentence the declaration already makes: nothing measured reads those
    # bytes back, so they are not part of what a verdict is about.
    tree=$(gate_measured_tree_of "${head}^{tree}" 2>/dev/null) || tree=""
    if [ -z "$tree" ]; then
        GATE_DOCS_ONLY_WHY="docs-only? no — ${head} resolves to no tree — full bank"
        return 1
    fi
    # THE KEY AND THE DELTA MUST BE ABOUT THE SAME BYTES. The row is keyed on
    # the MEASURED tree (`gate_measured_tree`, which reads through `git add -A`
    # and subtracts every declared derived path) and the delta above is taken
    # between MEASURED trees too, so the only thing this equality can now catch
    # is the thing it was always for: a DIRTY working tree, where `git add -A`
    # sees bytes HEAD does not carry. It used to compare against HEAD's RAW
    # tree, which on a declaring product can never equal the measured one — so
    # the guard fired on every clean checkout that declared anything, and the
    # road was closed to exactly the products it was built for. Asked rather
    # than assumed, and now asked of the same arithmetic on both sides.
    measured=$(gate_measured_tree 2>/dev/null) || measured=""
    if [ "$measured" != "$tree" ]; then
        GATE_DOCS_ONLY_WHY="docs-only? no — the measured WORKING tree (${measured:-unreadable}) is not HEAD's measured tree (${tree}), so there is an uncommitted byte in the delta the row would key on — full bank"
        return 1
    fi
    gate_docs_only_source "$head" >/dev/null || return 1
    delta=$(git diff-tree -r --name-only "$GATE_DOCS_ONLY_SOURCE" "$tree" 2>/dev/null) || delta=""
    if [ -z "$delta" ]; then
        GATE_DOCS_ONLY_WHY="docs-only? no — HEAD's tree IS the source tree ${GATE_DOCS_ONLY_SOURCE}, so there is nothing to reuse and a row already stands — full bank"
        return 1
    fi
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        case "$p" in
        *[[:space:]]*)
            GATE_DOCS_ONLY_WHY="docs-only? no — a changed path carries whitespace and this reader cannot name it — full bank"
            return 1
            ;;
        esac
        if ! gate_docs_only_admits "$p"; then
            GATE_DOCS_ONLY_WHY="docs-only? no — ${p} is not a docs-only path — full bank"
            return 1
        fi
        n=$((n + 1))
        needles="${needles}${needles:+ }${p} ${p##*/}"
    done <<EOF
$delta
EOF
    if [ "$n" -eq 0 ]; then
        GATE_DOCS_ONLY_WHY="docs-only? no — the delta could not be read — full bank"
        return 1
    fi
    # THE READERS, DERIVED PER PATH. `static` ALWAYS: the adr-census,
    # dangling-docs, goalpost-census, queue-index and archaeology legs all read
    # `docs/`, and the house-rules engine reads its own `doc:` targets there.
    readers="static"
    while IFS= read -r hit; do
        [ -n "$hit" ] || continue
        file=${hit%%:*}
        case "$file" in
        apps/* | config/*)
            GATE_DOCS_ONLY_WHY="docs-only? no — ${hit#* } is read literally at ${hit%% *} — full bank"
            return 1
            ;;
        quality/*) engine=1 ;;
        esac
    done <<EOF
$(gate_docs_only_literal_reads $needles)
EOF
    if [ "$engine" = "1" ]; then
        readers="${readers},full-house-rules"
    fi
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        readers="${readers},${d}"
    done <<EOF
$(gate_docs_only_drives $delta)
EOF
    GATE_DOCS_ONLY_N="$n"
    GATE_DOCS_ONLY_READERS="$readers"
    return 0
}

# ---- a DRIVE's verdict, keyed on what the drive DRIVES ------------------
#
# THE MEASUREMENT THAT OPENED THIS. A full bank spent 1887 s in the selftest
# leg, of which the thirty shell drives were 1663 s — re-driven in full on every
# run, whatever had moved. Four of them were 1116 s of that. A rung that touches
# only `apps/` moves nothing any of the other twenty-six reads, and drove them
# all anyway.
#
# THE SHAPE, AND WHY IT IS NOT THE FULL ROW'S. A full verdict is keyed on the
# MEASURED TREE, which is the right key for a claim about a whole tree and the
# wrong one here: an `apps/`-only rung moves the measured tree, so every drive
# would re-key and nothing would ever be reused. A drive's verdict is a claim
# about ITS OWN INPUTS, so its key is those inputs and nothing else.
#
# A DRIVE DECLARES WHAT IT DRIVES, AND THE DECLARATION IS CROSS-CHECKED BY
# DERIVATION. One line — `# drives: <path> [<path>…]`, checkout-relative paths
# or globs, in the file's first forty lines — is THE KEY. Derivation alone was
# rejected because a drive reaches its subjects by `source`, by `cp -R` into a
# clone, by `awk`-extracting one function and by `uv run python -m quality.gate`,
# and no grammar over "paths spelled in the file" sees a sourced library's own
# `source`. A bare marker was rejected too: a declaration nobody reads is
# `FULL_LEGS` before it was compared. So the marker is the key and the
# DERIVATION IS THE FLOOR — every checkout path the body spells must be covered
# by a declared one, or the leg refuses that drive at exit 2, naming it.
#
# WHAT "EVERY CHECKOUT PATH" MEANS, and it used to mean less than it said. The
# grammar read three typed prefixes — `scripts/<x>.(sh|py)`, `quality/…` and
# `apps/…` — so a drive could read `docs/product/build-contract.md`,
# `compose.yaml`, `deploy/…`, `frontend/…`, `pyproject.toml` or
# `.secrets.baseline` undeclared, and its verdict was then REUSED over changed
# bytes: three such sites were standing when this was widened
# (`test_list_legs.sh` comparing the listing against build-contract.md,
# `test_db_zsh.sh` and `test_db_pin.sh` reading compose.yaml). The prefix list
# is now DERIVED from the measured tree itself — every top-level entry in the
# listing, directories as `<dir>/…` and files as their own whole name — so a
# new top level joins the floor the day it is committed and nothing here has to
# be remembered.
#
# THREE THINGS THE FLOOR DOES NOT COUNT, each narrower than "literally spelled"
# and each argued rather than assumed:
#
#   A PATH THAT IS NOT IN THE MEASURED TREE. A subject has to exist to be
#   reached. Most drives spell paths that are PLANT NAMES inside a throwaway
#   clone (`apps/widgets/models.py`, `scripts/plant.sh`) and a floor that
#   demanded those be declared would demand a declaration that expands to
#   nothing, which is itself a refusal — a deadlock, not a belt.
#
#   AN OCCURRENCE PRECEDED BY `/`. `"$d/apps/example/models.py"` is a path
#   inside somebody else's root; `scripts/loop_tier.sh` at the start of a word is
#   this checkout's. The two are told apart by the character in front, which is
#   the only signal on the line.
#
#   AN OCCURRENCE PRECEDED BY A WORD CHARACTER, for the same reason a census
#   anchors on a boundary rather than a substring.
#
# ALWAYS IN THE KEY, whatever the marker says: the drive file itself and the
# `drive_preamble.sh` BESIDE IT. Both are digested from their BYTES rather than
# through the tree, because a drive set under `mktemp -d` — which is how this
# leg's own drive drives it — has no blob in any tree at all.
#
# WHAT A REUSE RESTS ON, said out loud: an equality asked of git over the
# measured tree, plus the two files' bytes, plus THIS MACHINE'S OWN CLAIM —
# which is the image id on a verifier box and bash/git/uname anywhere else
# (`drive_machine_digest`, below, argues both halves). A machine change is NOT
# in the key beyond that claim (docker, a Postgres image, a CLI upgrade — and on
# a box, anything `setup.sh` changed after the bake), and the answer to one is
# `DJB_SELFTEST_NO_REUSE=1` once — which runs everything and still banks,
# because a forced green is strictly newer evidence for the same key.
DRIVE_KEY_SCHEMA=drive-v1
DRIVE_MARKER_LINES=40

# drive_check_sh_sources <path to check.sh> — the libraries `scripts/check.sh`
# SOURCES, one per line, checkout-relative. Empty (exit 1) when the file cannot
# be read or sources nothing, which is the caller's refusal to make.
#
# WHY A DECLARATION OF `scripts/check.sh` HAS TO EXPAND. `check.sh` is nine
# `. scripts/<lib>.sh` lines deep, and a drive that declares it and runs it is
# driving all ten files. Keyed on `check.sh` alone, a byte moved in
# `gate_refuse.sh` — the refusal grammar every leg prints through — left every
# such drive's key IDENTICAL, so the leg reused a verdict for bytes the run had
# never seen. That is the one failure a reuse may not have, and it was
# invisible because the declaration looked complete.
#
# DERIVED FROM THE FILE, never listed: every `. scripts/<x>.sh` the gate
# spells, at any indent, including the ones inside a subshell (`lifecycle.sh`)
# and the guarded one at the top (`gate_refuse.sh`). A superset is the safe
# direction — an extra file in the key costs a re-key, a missing one costs a
# reuse that lied.
drive_check_sh_sources() {
    local file=$1
    [ -r "$file" ] || return 1
    sed -n 's|^[[:space:]]*\.[[:space:]]\{1,\}\(scripts/[A-Za-z0-9_./-]*\.sh\).*|\1|p' "$file" |
        LC_ALL=C sort -u
}

# ---- the machine half, and why a BOX declares an IMAGE ----------------------
#
# A MEMO THAT OUTLIVES ITS MACHINE IS THE WHOLE PROBLEM. `uname -sr` is Darwin
# on this laptop and Linux on every verifier box, so a drive row banked here can
# never hit there — which is correct, and which also means a fresh box arrives
# with an empty ledger and re-drives all thirty. Measured on the first on-box
# bank: thirty drives, none reused.
#
# THE FIX IS NOT TO WIDEN THE KEY — IT IS TO NAME THE CLAIM A BOX CAN MAKE. Two
# boxes cut from ONE IMAGE have the same bash, the same git, the same kernel and
# the same everything else the bake installed; the image id is a single token
# that says so, and it is a STRONGER claim than three version strings, not a
# weaker one. So on a box the machine half is `image <ami>` and the three lines
# are not read at all; everywhere else it is the three lines, exactly as before.
#
# THE BOX CANNOT BE ASKED THE NAME OF THE IMAGE IT WAS CUT FROM. IMDS would
# answer, but IMDS cannot be planted by a drive and a key input no drive can
# move is a key input nobody can prove. So the launch seam WRITES it:
# `deploy/verifier/user-data.yaml.in` lands `/etc/djb/image-id` at boot from the
# `$image` `scripts/verifier_box.sh`'s `cmd_up` already holds, and this reads
# that file. One line, root-owned, 0644 — the same shape as the three files
# `/etc/verifier/` already carries for the reaper.
#
# ABSENT IS THE ORDINARY CASE AND IS NEVER AN ERROR: no file means this is not a
# box, and the host digest is the answer. UNREADABLE IS EXIT 1, and it composes
# to the leg's could-not-look — a machine that has the file and will not show it
# is a machine whose identity is undecided, and an undecided key that silently
# fell back to the host digest would be a Mac row and a box row colliding under
# one label, which is the one failure this whole mechanism exists to prevent.
#
# THE OVERRIDE IS THE DRIVES', AND IT IS REFUSED WHEN RELATIVE, for
# `gate_ledger_path`'s reason one axis over: a machine file resolved against
# whatever directory a caller left behind is a key input nobody can name.
DRIVE_MACHINE_FILE_DEFAULT=/etc/djb/image-id
drive_machine_file() {
    if [ -n "${DJB_DRIVE_MACHINE_FILE:-}" ]; then
        case "${DJB_DRIVE_MACHINE_FILE}" in
        /*)
            printf '%s\n' "$DJB_DRIVE_MACHINE_FILE"
            return 0
            ;;
        *)
            echo "note: DJB_DRIVE_MACHINE_FILE='${DJB_DRIVE_MACHINE_FILE}' is relative — refusing it." >&2
            return 1
            ;;
        esac
    fi
    printf '%s\n' "$DRIVE_MACHINE_FILE_DEFAULT"
}

# drive_machine_label — `image:<ami>` on a box, `host:<12 hex>` anywhere else;
# exit 1 when the machine could not be digested at all. It is what the leg
# PRINTS beside a REUSED or a miss, so a reader can tell a row that travelled
# from a row that was earned here without opening the ledger.
#
# MEMOISED THROUGH THE ENVIRONMENT, for `drive_machine_digest`'s reason and in
# the same breath: both are filled by one pass so a leg pays one read.
DRIVE_MACHINE_LABEL=${DRIVE_MACHINE_LABEL:-}
drive_machine_label() {
    drive_machine__fill || return 1
    printf '%s\n' "$DRIVE_MACHINE_LABEL"
}

# drive_machine_digest — the machine half of every drive key. MEMOISED THROUGH
# THE ENVIRONMENT rather than a shell global, because every caller reaches
# `drive_key` through `$(...)`: a global set inside that subshell is gone with
# it, and this was four process starts per drive for an answer that cannot
# change inside one leg. It is exported so the memo survives the subshell that
# fills it.
DRIVE_MACHINE_DIGEST=${DRIVE_MACHINE_DIGEST:-}
drive_machine_digest() {
    drive_machine__fill || return 1
    printf '%s\n' "$DRIVE_MACHINE_DIGEST"
}

# ONE FILLER FOR BOTH, so a label and a digest can never disagree about which
# machine this is. Either both are set or neither is, and the caller's exit 1 is
# the only other outcome.
drive_machine__fill() {
    [ -z "${DRIVE_MACHINE_DIGEST:-}" ] || [ -z "${DRIVE_MACHINE_LABEL:-}" ] || return 0
    local file ami
    file=$(drive_machine_file) || return 1
    if [ -e "$file" ]; then
        # THE READ IS THE TEST. `[ -r ]` answers about permission bits and says
        # nothing about a directory, a dangling symlink or a file on a mount
        # that has gone away — all of which are "the file is there and I cannot
        # digest it", which is the refusal this branch owes.
        ami=$({ tr -d ' \t\r' <"$file" | sed -n '1p'; } 2>/dev/null) || return 1
        [ -n "$ami" ] || return 1
        DRIVE_MACHINE_DIGEST=$(printf 'image %s\n' "$ami" | sha256_of) || return 1
        DRIVE_MACHINE_LABEL="image:${ami}"
    else
        DRIVE_MACHINE_DIGEST=$({
            bash --version 2>/dev/null | sed -n '1p'
            git --version 2>/dev/null
            uname -sr 2>/dev/null
        } | sha256_of) || return 1
        DRIVE_MACHINE_LABEL="host:$(printf '%s' "$DRIVE_MACHINE_DIGEST" | cut -c1-12)"
    fi
    export DRIVE_MACHINE_DIGEST DRIVE_MACHINE_LABEL
}

# drive_marker_line <file> — the declaration line, verbatim; exit 1 if the file
# carries none in its first `DRIVE_MARKER_LINES` lines.
drive_marker_line() {
    local out
    [ -r "$1" ] || return 1
    out=$(awk -v n="$DRIVE_MARKER_LINES" '
        NR > n { exit }
        /^#[[:space:]]*drives:/ { print; exit }
    ' "$1")
    [ -n "$out" ] || return 1
    printf '%s\n' "$out"
}

# drive_cites_line <file> — the CITATION line, verbatim; exit 1 when the file
# carries none in its first `DRIVE_MARKER_LINES` lines.
#
# A CITATION IS NOT A SUBJECT, and the floor cannot tell them apart. The floor
# reads paths the body SPELLS, and a drive that explains itself spells paths it
# never touches: `test_rung_start.sh` names `scripts/tests/test_fe_leg.sh` as
# "the shim pattern it uses for the same reason", and `test_verify_start.sh`
# names `scripts/check.sh` in three paragraphs about what a clone of a verifier
# cannot run. Declared, those become key inputs: every rung that moves a byte in
# the gate re-drives a drive that never opens it, which is the reuse this whole
# mechanism exists to earn.
#
# SO A CITATION IS DECLARED TOO, on its own line, and SUBTRACTED from what the
# floor demands — never from what the key holds, because a cited path is not in
# the key at all. It is a valve, and it obeys this repository's valve rules:
# it is typed, it is counted, and the leg PRINTS the count beside the drive, so
# a drive quietly citing its way out of its own subjects is visible rather than
# silent. `# cites: <path> [<path>…]`, the same grammar as `# drives:`.
#
# WHAT IT CANNOT DO: a cited path is never added to the key, so citing a path
# the body really does READ is a silent reuse of exactly the kind the floor
# refuses. That is the declared cost of the valve, and it is why the count is
# printed rather than merely allowed.
drive_cites_line() {
    local out
    [ -r "$1" ] || return 1
    out=$(awk -v n="$DRIVE_MARKER_LINES" '
        NR > n { exit }
        /^#[[:space:]]*cites:/ { print; exit }
    ' "$1")
    [ -n "$out" ] || return 1
    printf '%s\n' "$out"
}

# drive__expand <listing> <pattern> — every blob the declared path covers, as
# `<sha> <path>`, sorted. The listing is one `git ls-tree -r <tree>` capture,
# taken once per leg: a git call per declared path per drive is thirty times the
# work for the same answer. Empty output means the path is in no tree, which is
# the caller's refusal to make.
drive__expand() {
    awk -v pat="$2" '
    function to_ere(p,   out, i, ch) {
        sub(/\/$/, "", p)
        out = ""
        for (i = 1; i <= length(p); i++) {
            ch = substr(p, i, 1)
            if (ch == "*") {
                if (substr(p, i + 1, 1) == "*") { out = out ".*"; i++ }
                else { out = out "[^/]*" }
            } else if (index(".[]^$+?(){}|\\", ch) > 0) {
                out = out "\\" ch
            } else { out = out ch }
        }
        return out
    }
    BEGIN { re = to_ere(pat) }
    {
        tab = index($0, "\t")
        if (tab == 0) next
        path = substr($0, tab + 1)
        if (path ~ ("^" re "$") || path ~ ("^" re "/")) printf "%s %s\n", $3, path
    }
    ' "$1" | LC_ALL=C sort
}

# drive_drawer_globs — the reserved DRAWER patterns, read from their ONE home.
#
# THE HOME IS `scripts/divergence_census.sh`'s `DRAWER_GLOBS`, and it says so
# itself: "one home for `which paths are the drawers`, not two of either". The
# line is READ rather than sourced — the census is an executable whose body
# runs a census — and it is read as TEXT, never expanded: every member is a
# pathname pattern the shell would happily glob against the tree it is standing
# in, which is the exact defect the census's own `set -f` exists to close.
#
# EMPTY IS A REFUSAL AND NEVER A NARROWER SET. A caller that could not read the
# line must say so at exit 2, because the alternative — judging no path as a
# drawer — is the silently-passing direction.
drive_drawer_globs() {
    [ -r scripts/divergence_census.sh ] || return 1
    awk -F"'" '/^DRAWER_GLOBS=/ { print $2; exit }' scripts/divergence_census.sh |
        grep . || return 1
}

# drive_absorbed_paths — the fold's ABSORBED list, read from its one home.
#
# THE HOME IS `scripts/pm_fold.sh`'s `FOLD_ABSORBED_PATHS`, and the class it
# names is exactly the one this reader wants: a derived file written from
# OUTSIDE this checkout that no step of the fold can regenerate, so it is the
# one kind of declared path that can legitimately be missing from a tree. The
# assignment is READ rather than sourced — pm_fold is an executable whose body
# folds — and the reader handles the one-line and the multi-line quoted form,
# because `DERIVED_PATHS` beside it is already multi-line and this list is a
# strict subset of that one.
#
# UNREADABLE IS NOT "EVERYTHING IS ABSORBED". The caller falls back to its
# refusal when this answers nothing, which is the failing-closed direction.
drive_absorbed_paths() {
    [ -r scripts/pm_fold.sh ] || return 1
    awk '
    BEGIN { q = sprintf("%c", 39); pfx = "FOLD_ABSORBED_PATHS=" q }
    {
        line = $0
        if (!inside) {
            if (index(line, pfx) != 1) next
            inside = 1
            line = substr(line, length(pfx) + 1)
        }
        p = index(line, q)
        if (p > 0) { line = substr(line, 1, p - 1); done = 1 }
        if (length(line)) print line
        if (done) exit
    }
    ' scripts/pm_fold.sh | grep . || return 1
}

# drive_absorbed_path <path> — true when that exact path is in the list above.
drive_absorbed_path() {
    drive_absorbed_paths 2>/dev/null | grep -xF -- "$1" >/dev/null
}

# drive__uncovered <listing> <declared paths> <drive file> <drawer globs> — the
# FIRST checkout path the body spells that no declared path covers, or nothing
# at all. The three exclusions are argued in this section's header.
#
# THE FOURTH ARGUMENT IS THE ONE EXCEPTION TO THE FIRST EXCLUSION, and the
# first consumer paid for it. "A path that is not in the measured tree" is
# skipped because most absent paths a body spells are plant names inside a
# throwaway clone — but a RESERVED DRAWER path is absent on the TEMPLATE and
# present on every product that uses the drawer, so the floor judged
# `scripts/local/legs` on their tree and not on ours: three drives keyed clean
# here and exited 2 at their bank, on bytes nobody had changed. A drawer path
# is therefore judged AS IF IT EXISTED, on every tree, so the template's own
# bank meets the refusal the product would. The cost is one line per drive —
# a drawer path a drive only spells goes on its `# cites:` line — and that is
# the honest declaration either way: a drive that PLANTS a drawer in a clone is
# not reading the tree's own.
drive__uncovered() {
    awk -v decls="$2" -v drawers="$4" '
    # SHELL-CASE SEMANTICS, NOT `to_ere`s. The census matches these patterns
    # with `case`, where a single `*` crosses `/` — `*.local.md` is meant to
    # reach `docs/product/instruments.local.md`. `to_ere` reads a single `*` as
    # `[^/]*`, which is right for a DECLARATION and wrong for these three.
    function drawer_ere(p,   out, i, ch) {
        out = ""
        for (i = 1; i <= length(p); i++) {
            ch = substr(p, i, 1)
            if (ch == "*") {
                out = out ".*"
                while (substr(p, i + 1, 1) == "*") i++
            } else if (index(".[]^$+?(){}|\\", ch) > 0) {
                out = out "\\" ch
            } else { out = out ch }
        }
        return out
    }
    # A HIT IS TESTED TWICE — bare, and with a trailing `/`. `**/local/**`
    # becomes `.*/local/.*`, which reaches `scripts/local/legs` and NOT the
    # bare directory `scripts/local`; the trailing slash is what makes the
    # directory itself a drawer too, without widening the pattern.
    function is_drawer(p,   i) {
        for (i = 1; i <= dwn; i++) {
            if (p ~ ("^" dwre[i] "$")) return 1
            if ((p "/") ~ ("^" dwre[i] "$")) return 1
        }
        return 0
    }
    function to_ere(p,   out, i, ch) {
        sub(/\/$/, "", p)
        out = ""
        for (i = 1; i <= length(p); i++) {
            ch = substr(p, i, 1)
            if (ch == "*") {
                if (substr(p, i + 1, 1) == "*") { out = out ".*"; i++ }
                else { out = out "[^/]*" }
            } else if (index(".[]^$+?(){}|\\", ch) > 0) {
                out = out "\\" ch
            } else { out = out ch }
        }
        return out
    }
    BEGIN {
        n = split(decls, dd, " ")
        for (i = 1; i <= n; i++) re[i] = to_ere(dd[i])
        dwn = split(drawers, dw, " ")
        for (i = 1; i <= dwn; i++) dwre[i] = drawer_ere(dw[i])
    }
    NR == FNR {
        tab = index($0, "\t")
        if (tab == 0) next
        p = substr($0, tab + 1)
        m = split(p, seg, "/")
        acc = ""
        for (k = 1; k <= m; k++) { acc = (k == 1 ? seg[1] : acc "/" seg[k]); intree[acc] = 1 }
        # THE PREFIX LIST IS THE TOP LEVEL OF THE TREE ITSELF, derived here rather than
        # typed: a top-level DIRECTORY contributes `<dir>/...` and a top-level
        # FILE contributes its own whole name. A typed list was the old
        # grammar defect — it read `scripts/*.(sh|py)`, `quality/` and
        # `apps/` and nothing else, so `docs/product/build-contract.md`,
        # `compose.yaml` and `.secrets.baseline` were reachable by a body and
        # invisible to the floor.
        if (m > 1) {
            if (!(seg[1] in topdir)) { topdir[seg[1]] = 1; dlist[++dn] = to_ere(seg[1]) }
        } else {
            if (!(p in topfile)) { topfile[p] = 1; flist[++fn] = to_ere(p) }
        }
        next
    }
    FNR == 1 {
        # A DIRECTORY HIT MUST BE A PATH, not the bare word. `docs` and
        # `config` are ordinary English in a comment; `docs/product/queue.md`
        # is a file somebody reads. A top-level FILE has no `/` to require, so
        # it is matched whole and the `intree` test below is what keeps it
        # honest.
        da = ""
        for (i = 1; i <= dn; i++) da = da (da ? "|" : "") dlist[i]
        fa = ""
        for (i = 1; i <= fn; i++) fa = fa (fa ? "|" : "") flist[i]
        if (da == "" && fa == "") { exit }
        if (da == "") pat = "(" fa ")"
        else if (fa == "") pat = "((" da ")(/[A-Za-z0-9_.-]+)+)"
        else pat = "((" da ")(/[A-Za-z0-9_.-]+)+|(" fa "))"
    }
    {
        line = $0
        while (match(line, pat)) {
            hit = substr(line, RSTART, RLENGTH)
            before = (RSTART > 1) ? substr(line, RSTART - 1, 1) : ""
            line = substr(line, RSTART + RLENGTH)
            if (before ~ /[A-Za-z0-9_\/.-]/) continue
            if (!(hit in intree) && !is_drawer(hit)) continue
            covered = 0
            for (i = 1; i <= n; i++) {
                if (hit ~ ("^" re[i] "$") || hit ~ ("^" re[i] "/")) { covered = 1; break }
            }
            if (!covered) { print hit; exit }
        }
    }
    ' "$1" "$3"
}

# drive_key <drive file> <tree> <listing> — `ok <key> <parts>` on stdout, or
# `err <reason>`; exit 0 or 1.
#
# IT PRINTS THE ANSWER RATHER THAN SETTING A GLOBAL because every caller reads
# it through `$(...)`, where a global the callee set is gone with the subshell.
# `<parts>` is `<label>:<12 hex>` per key component, comma-joined — the row
# carries it so that a MISS can name WHICH input moved rather than only that one
# did. Nothing ranks or trusts it; it is an attributor's evidence, not a key.
drive_key() {
    local file=$1 tree=$2 listing=$3
    local marker decls d preamble parts="" text digest uncovered one label sorted sourced basename cites cites_line cited_count machine_label drawers
    [ -r "$file" ] || {
        printf 'err the drive file %s is not readable\n' "$file"
        return 1
    }
    [ -r "$listing" ] || {
        printf 'err the measured tree listing for %s could not be read\n' "$tree"
        return 1
    }
    marker=$(drive_marker_line "$file") || {
        printf 'err no `# drives:` line in its first %s lines — a drive declares what it drives\n' \
            "$DRIVE_MARKER_LINES"
        return 1
    }
    decls=${marker#*drives:}
    if [ -z "$(printf '%s' "$decls" | tr -d ' 	')" ]; then
        printf 'err its `# drives:` line names no path\n'
        return 1
    fi
    case "$file" in
    */*) preamble="${file%/*}/drive_preamble.sh" ;;
    *) preamble="drive_preamble.sh" ;;
    esac
    [ -r "$preamble" ] || {
        printf 'err there is no drive_preamble.sh beside %s — it is always in the key\n' "$file"
        return 1
    }
    # A DECLARATION OF `scripts/check.sh` CARRIES ITS LIBRARIES WITH IT. The
    # expansion is made here, once, before the floor and before the key, so the
    # two read the same set: a drive that declares the gate is driving the gate
    # AND the nine files it sources, and neither the coverage question nor the
    # digest may be asked about a smaller set than the run touched. The reader
    # is `drive_check_sh_sources`, and its argument is above it.
    case " $decls " in
    *" scripts/check.sh "* | *" scripts/ "* | *" scripts "*)
        sourced=$(drive_check_sh_sources "scripts/check.sh") || sourced=""
        [ -z "$sourced" ] || decls="${decls} $(printf '%s' "$sourced" | tr '\n' ' ')"
        ;;
    esac
    # THE FLOOR IS ASKED ABOUT THE DECLARED PATHS *AND* THE TWO THAT ARE ALWAYS
    # IN THE KEY. Every drive's first executable line sources the preamble beside
    # it and most name themselves in their own `--list` grammar; requiring those
    # two to be re-declared would be thirty copies of a line the key already
    # carries, and a declaration that adds nothing is the one a reader stops
    # reading.
    # THE CITATIONS ARE SUBTRACTED FROM THE FLOOR AND FROM NOTHING ELSE. They
    # join the set the floor is asked about, so a spelled citation is covered;
    # they do NOT join `$sorted` below, so no cited path reaches the key.
    cites=""
    cites_line=$(drive_cites_line "$file") && cites=${cites_line#*cites:}
    cited_count=$(printf '%s' "$cites" | tr ' 	' '\n\n' | grep -c . || true)
    drawers=$(drive_drawer_globs) || {
        printf 'err the reserved drawer globs could not be read from scripts/divergence_census.sh (`DRAWER_GLOBS=`) — the floor cannot judge a drawer path it cannot name, and judging none is the silently-passing direction\n'
        return 1
    }
    uncovered=$(drive__uncovered "$listing" "$decls $cites $file $preamble" "$file" "$drawers")
    if [ -n "$uncovered" ]; then
        printf 'err its body spells %s and its `# drives:` line does not cover it (a path it only CITES goes on a `# cites:` line)\n' "$uncovered"
        return 1
    fi
    # THE TWO ALWAYS-IN-THE-KEY COMPONENTS ARE LABELLED `self` AND `preamble` IN
    # THE KEY TEXT, and by their PATH in `parts`. The difference is load-bearing:
    # a key that carried the drive's own absolute path would make the same bytes
    # under two directories two different keys — which is exactly what a scratch
    # drive set under `mktemp -d` is — while a miss line that said `self moved`
    # would name nothing a reader can open.
    # THE DRIVE'S NAME IS IN THE KEY, and it is not the same thing as its path.
    # Everything else the key holds is CONTENT — the marker, the two files'
    # bytes, the declared blobs, the machine — so two drives whose content
    # happens to be identical key identically and the second REUSES the first's
    # verdict under its own name. That is not hypothetical: a harness of stub
    # drives (`test_list_legs.sh`'s shard census, every stub `exit 0`) had every
    # member after the first come back REUSED, and the leg reported a run for a
    # drive it never invoked. The NAME is stable across directories — a scratch
    # set under `mktemp -d` carries the same names — which is exactly why the
    # PATH is still absent from the key text and the header above still holds.
    local basename=${file##*/}
    basename=${basename#test_}
    basename=${basename%.sh}
    # THE CITATION LINE IS IN THE KEY TEXT, and the cited PATHS are not. Moving
    # a path from `# drives:` to `# cites:` must re-key — it is a claim that the
    # drive stopped reading that file — while a byte moving inside a cited file
    # must not, which is the whole point of citing it.
    text="${DRIVE_KEY_SCHEMA}
name ${basename}
marker ${marker}
cites ${cites_line:-<none>}"
    for label in self:"$file" preamble:"$preamble"; do
        one=$(sha256_of "${label#*:}") || {
            printf 'err %s could not be digested\n' "${label#*:}"
            return 1
        }
        text="${text}
${label%%:*} ${one}"
        parts="${parts}${parts:+,}${label#*:}:$(printf '%s' "$one" | cut -c1-12)"
    done
    # shellcheck disable=SC2086
    sorted=$(printf '%s\n' $decls | LC_ALL=C sort -u)
    for d in $sorted; do
        one=$(drive__expand "$listing" "$d")
        if [ -z "$one" ]; then
            # AN ABSORBED DERIVED OUTPUT KEYS AS `absent`, AND NOTHING ELSE
            # DOES. `FOLD_ABSORBED_PATHS` is the fold's one-member class of
            # derived file WRITTEN FROM OUTSIDE THIS CHECKOUT that no step
            # here can regenerate (scripts/pm_fold.sh) — `scripts/test_impact
            # .json`, the bank's own output, which the release does not ship.
            # So on every consumer it is absent until their first green bank
            # writes it, three drives declare it, and a declared path that
            # expands to nothing was a refusal: the bank could not go green
            # because the drives were exit 2, and the drives were exit 2
            # because the bank had not gone green. A deadlock, and it was the
            # first consumer's.
            #
            # `absent` IS A KEY COMPONENT AND NOT A SUBTRACTION. The path
            # stays in the key text, so the day the map appears the key moves
            # and every verdict that was banked without it misses — which is
            # the property the refusal was protecting and the reason this is
            # not a `# cites:` line. `pm_fold.sh`'s own argument for keeping
            # the map typed in `DERIVED_PATHS` says the same thing: a path a
            # measurement reads is a path the key must carry.
            if drive_absorbed_path "$d"; then
                digest="absent"
                text="${text}
${d} ${digest}"
                parts="${parts},${d}:${digest}"
                continue
            fi
            printf 'err the declared path %s expands to nothing in the measured tree — never a silently narrower key\n' "$d"
            return 1
        fi
        digest=$(printf '%s\n' "$one" | sha256_of) || {
            printf 'err %s could not be digested\n' "$d"
            return 1
        }
        text="${text}
${d} ${digest}"
        parts="${parts},${d}:$(printf '%s' "$digest" | cut -c1-12)"
    done
    one=$(drive_machine_digest) || {
        printf 'err this machine could not be digested\n'
        return 1
    }
    # THE `parts` LABEL STAYS `machine:` AND CARRIES THE DIGEST'S FIRST 12 HEX,
    # on a box exactly as on a laptop. `drive_moved_component` is an attributor
    # over these pairs and knows `machine` by name; a label that changed shape
    # on a box would make "the machine moved" unreadable on exactly the machines
    # this change exists for. WHICH machine it is goes in the FIFTH field below,
    # where nothing keys on it.
    text="${text}
machine ${one}"
    parts="${parts},machine:$(printf '%s' "$one" | cut -c1-12)"
    machine_label=$(drive_machine_label) || machine_label=unstated
    digest=$(printf '%s\n' "$text" | sha256_of) || {
        printf 'err the key could not be digested\n'
        return 1
    }
    # THE CITED COUNT IS A FOURTH FIELD, NOT A PART. `parts` is the attributor's
    # per-input digest list and a component named `cites` in it would turn a
    # valve into a "moved input" in the miss line. The leg reads this field and
    # prints it beside the drive, which is what makes the valve counted.
    # AND THE MACHINE LABEL IS A FIFTH, for the same reason one axis over: it is
    # not a key input — the DIGEST above already is — it is the one word that
    # tells a reader whether the row they are about to reuse was earned on this
    # laptop or on a box of some image, and the leg prints it beside every
    # REUSED and every miss.
    printf 'ok %s:%s %s cites=%s machine=%s\n' \
        "$DRIVE_KEY_SCHEMA" "$digest" "$parts" "${cited_count:-0}" "${machine_label:-unstated}"
}

# drive_ledger_record <key> <name> <took> <tree> <parts> — one appended line.
#
# SAME FILE, NEW KIND IN FIELD 3. `gate_ledger_lookup` matches ` <tree> full `
# and `gate_run_lookup` reads field 4 of a `full` row, so neither can reach one
# of these however a key is chosen — including a key that IS a tree sha, which
# `test_loop_ledger.sh` plants on purpose. The partition's separate file is
# deliberately NOT the precedent here: one ledger, one `gate_local_path`, one
# shared-across-worktrees rule.
drive_ledger_record() {
    local key=$1 name=$2 took=$3 tree=$4 parts=$5 path
    path=$(gate_ledger_path) || return 1
    printf '%s %s drive %s %s exit=0 took=%s tree=%s parts=%s\n' \
        "$GATE_LEDGER_SCHEMA" "$key" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$name" "$took" "$tree" "$parts" >>"$path"
}

# drive_ledger_lookup <key> → the most recent drive row at this key, exit 0; 1
# when nothing has been banked for it.
drive_ledger_lookup() {
    local key=$1 path line
    path=$(gate_ledger_path) || return 1
    [ -f "$path" ] || return 1
    line=$(grep -F " ${key} drive " "$path" | grep "^$GATE_LEDGER_SCHEMA " | tail -1)
    [ -n "$line" ] || return 1
    printf '%s\n' "$line"
}

# drive_ledger_last_for <name> → the most recent drive row for this drive at ANY
# key. It is what a MISS is attributed against, and it is why the row carries
# its parts: without a previous row there is nothing to diff, and the leg says
# so rather than inventing a reason.
drive_ledger_last_for() {
    local name=$1 path line
    path=$(gate_ledger_path) || return 1
    [ -f "$path" ] || return 1
    line=$(awk -v n="$name" '$1 == "v1" && $3 == "drive" && $5 == n { last = $0 } END { if (last != "") print last }' "$path")
    [ -n "$line" ] || return 1
    printf '%s\n' "$line"
}

# drive_row_parts <row> — the `parts=` field's value, or nothing.
# AN EOF READER, NEVER A PIPE INTO AN EARLY-EXIT awk. The producer here is one
# `printf` and could never fill a pipe buffer, and the shape is still the one
# `scripts/tests/test_pipefail_readers.sh` counts across this whole population —
# a census that admitted "this one is safe" would be a census nobody can read.
drive_row_parts() {
    awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^parts=/) { sub(/^parts=/, "", $i); v = $i } } END { if (v != "") print v }' <<EOF
$1
EOF
}

# drive_moved_component <old parts> <new parts> — the first key component whose
# digest differs, by NAME, so the miss line can say which input moved. Every
# component's name is a path (the drive file, the preamble beside it, each
# declared path) except `machine`, which is bash/git/uname.
drive_moved_component() {
    awk -v oldp="$1" -v newp="$2" '
    BEGIN {
        no = split(oldp, o, ",")
        for (i = 1; i <= no; i++) {
            k = o[i]; sub(/:[^:]*$/, "", k)
            v = o[i]; sub(/^.*:/, "", v)
            od[k] = v
        }
        nn = split(newp, nw, ",")
        for (i = 1; i <= nn; i++) {
            k = nw[i]; sub(/:[^:]*$/, "", k)
            v = nw[i]; sub(/^.*:/, "", v)
            seen[k] = 1
            if (!(k in od)) { print k; exit }
            if (od[k] != v) { print k; exit }
        }
        for (k in od) if (!(k in seen)) { print k; exit }
    }'
}

# ---- the partition's verdicts -----------------------------------------
#
# ONE MORE CONSUMER OF THE SAME PATTERN, and it lives here rather than in
# `quality/partition.py` for the reason the header states about this whole file:
# a verdict is a property of what was measured, and the rules for banking one
# have exactly one home. The partition's key is not a tree hash — it is
# `<closure hash>:<discovery digest>` (docs/product/partition-closure.md §4),
# both parts, because the closure's FILES are not the partition's whole input:
# platform behaviour reaches through discovery, so the population the walks
# return is part of the key or the skip is unsound.
#
# THE SAME THREE PROPERTIES HOLD. A row is only written by a complete green full
# run (`scripts/check.sh` records it after the second pytest pass); a stale key
# is a miss and never a partial match; and a key this file cannot parse is
# EXIT 2, not a miss — a mistyped invocation is never a silent skip.
#
# `DJB_PARTITION_LEDGER` points these at a scratch file, which is how §8's
# canaries forge a stale row without the forge ever being able to become a
# banked verdict.

#: `<64 hex>:<64 hex>` and nothing else. A row that is not this shape is not a
#: row this gate wrote, and reading it as an ordinary miss would turn a corrupt
#: ledger into a silent full run — which is the tolerable direction, but it is
#: also the direction in which nobody ever finds out.
PARTITION_KEY_RE='^[0-9a-f]{64}:[0-9a-f]{64}$'

partition_ledger_path() {
    if [ -n "${DJB_PARTITION_LEDGER:-}" ]; then
        printf '%s\n' "$DJB_PARTITION_LEDGER"
        return 0
    fi
    gate_local_path djb-partition-verdicts
}

# partition_ledger_record <key> — one line, appended, schema first.
partition_ledger_record() {
    local key=$1 path
    # `grep PATTERN >/dev/null`, NEVER `| grep -q`, and this is a measured class
    # rather than a style note (GQ-1's reproduction). `-q` makes grep exit the
    # instant it matches, which closes the pipe under the producer; a producer
    # that has more than the 64KiB pipe buffer still to write then takes SIGPIPE
    # and dies 141, and `set -o pipefail` hands 141 to the caller — a MATCH
    # reported as a failure, deterministically, above the buffer size. This
    # producer is one key and could never reach 64KiB, so the fix here is the
    # class being closed where it lives rather than a bug being repaired; the
    # site that could reach it is the one this file's neighbour fixed beside it.
    printf '%s' "$key" | grep -E "$PARTITION_KEY_RE" >/dev/null || {
        echo "partition_ledger_record: '$key' is not a partition key" >&2
        return 2
    }
    path=$(partition_ledger_path) || return 1
    printf '%s %s partition %s caller=%s\n' \
        "$GATE_LEDGER_SCHEMA" "$key" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(gate_caller)" >>"$path"
}

# partition_ledger_lookup <key> → the most recent matching line on stdout,
# exit 0; exit 1 when this key has no verdict; exit 2 when the ledger holds a
# line whose key is not a key.
partition_ledger_lookup() {
    local key=$1 path line bad
    path=$(partition_ledger_path) || return 1
    [ -f "$path" ] || return 1
    # The unparseable clause first, and over the WHOLE file: a corrupt row is a
    # statement about this ledger's health, not about the key being asked for,
    # so it outranks both the hit and the miss.
    bad=$(awk -v schema="$GATE_LEDGER_SCHEMA" '$1==schema && $3=="partition" && $2 !~ /^[0-9a-f]{64}:[0-9a-f]{64}$/ {print; exit}' "$path")
    if [ -n "$bad" ]; then
        echo "partition_ledger_lookup: the ledger holds a row whose key cannot be parsed: $bad" >&2
        return 2
    fi
    line=$(grep -F " $key partition " "$path" | grep "^$GATE_LEDGER_SCHEMA " | tail -1)
    [ -n "$line" ] || return 1
    printf '%s\n' "$line"
}

# ---- the LOOP ledger --------------------------------------------------------
#
# THE SAME PATTERN, ONE TIER DOWN. Two sentences in this file used to forbid
# exactly this — property 2 in the header, and the line above `gate_run_start`
# in the run-log section. Both are superseded HERE, in the same commit that
# makes them false, because a superseded sentence left standing is the drift
# class this whole file exists against. What is true now: `--fast` writes
# nothing anywhere; `--loop` records a verdict of its own, under a key that is
# strictly narrower than the full gate's and that can never be mistaken for one.
#
# NEITHER SUPERSESSION QUOTES THE CLAIM IT REPLACES, and that is deliberate
# rather than terse. A censused string counts wherever it appears, prose
# included — the first draft of this comment quoted the old sentence verbatim to
# be helpful and the drive that hunts for the stale claim found the quotation.
# A retired sentence is described, never re-spelled.
#
# WHY. A `--loop` run on a tree nothing has changed re-derives a deterministic
# result. The measurement that ordered this, taken on the sibling platform: 1283
# seconds re-spent to re-learn a verdict already earned. A verdict is a property
# of what was measured, and re-measuring identical inputs is not rigour, it is
# arithmetic performed twice.
#
# THE KEY IS THREE LINES, and each one is there because a verdict that ignored
# it would be a lie:
#
#   1. THE MEASURED TREE — `gate_measured_tree`, reused unchanged. The same
#      scratch-index content address the full gate keys on.
#   2. THE ENVIRONMENT FINGERPRINT — see `loop_env_fingerprint`. The suite runs
#      against a database, a bucket and a set of installed distributions, and
#      none of those is in the tree hash.
#   3. THE CANONICAL SCOPE — `scripts/loop_tier.sh`'s `LOOP_SCOPE_CANONICAL`:
#      the mode, the sorted scope labels and the digest of the always-on
#      declaration. THIS FIELD IS THE ONE THAT MAKES THE CACHE SOUND. A `--loop`
#      verdict is not a claim about a tree, it is a claim about a SELECTION over
#      a tree — so the same tree at two scopes is two keys, and a wider scope
#      can never read a narrower scope's row. Without this field, a verdict
#      banked while grading a one-app rung would be honoured by a rung that
#      touched `core`, and the second rung would have run nothing at all.
#
# THE MERGE-BASE, NOT MAIN'S TIP. The fingerprint carries the merge-base with
# `refs/heads/main`, which is the same base `secrets_scan_changed_files` derives
# the rung from. Keyed on main's TIP instead, every unrelated merge into local
# main invalidates every banked loop verdict in every worktree, and the cache
# never hits once — a dead cache that still costs a hash. Adopted with its
# reason, from the platform that measured it.
#
# WHAT `head=` BUYS THE KEY IS UNSTATED, AND THAT ABSENCE IS RECORDED RATHER
# THAN PAPERED OVER. The paragraph above argues the MERGE-BASE and nothing
# argues HEAD. Read against the other two inputs, HEAD looks like it can only
# ever invalidate: the measured tree already carries the CONTENT (it is a
# content address over a scratch index, working tree included), so two runs
# whose HEADs differ and whose trees agree measured identical bytes — and the
# key says miss anyway. The search for a reason was made on 2026-09-07 and came
# back empty; removing it is a KEY change, which invalidates every banked row in
# every checkout once and belongs to the partition-closure key redesign that
# will pay that cost once and deliberately, not here. What this file does about
# it TODAY is the attributor below: the row now carries the components, so the
# attributor can say `tree` where the honest answer is `tree`, and the reader
# stops being told two things moved when one did.
#
# WHAT THE `docs-only` COUNTER COUNTS, AND WHAT A SECOND OCCURRENCE LOOKS LIKE.
# The attributor's `tree` token now carries a line saying how many paths moved
# since the banked head and whether all of them were under `docs/`. A deferred
# piece of work — re-keying the pytest tier on the selection's own inputs so a
# ledger commit stops invalidating a suite verdict — is waiting on TWO field
# occurrences of the same shape, and the shape is narrow on purpose:
#
#   AN OCCURRENCE is a VERIFIER's ledger row whose `loop:` cell reads
#   `miss(tree)` and whose banner carried `docs-only: yes`, measured by ONE
#   `--loop` in a clone that `verify_start.sh` built as the union of a BANKED
#   branch and main. Occurrence 1 is on the record from 2026-09-07, read back
#   from that verifier's components line (env-file and dists equal; head,
#   merge-base and tree moved over two ledger commits) rather than from its
#   token, which could only say `unmatched`.
#
#   IT IS NOT AN OCCURRENCE when the verifier PLANTED the drift to see the
#   token work — a plant proves the instrument, never the frequency — and it is
#   not an occurrence when a BUILDER misses in its own worktree, where the tree
#   moved because the builder moved it and `docs-only` reads `no` by
#   construction (no commit since the banked head).
#
# Two occurrences dispatch the re-keying. One occurrence and a plant is one.
#
# THIS IS A CACHE AND IT IS NEVER A SECURITY BOUNDARY. A local file an agent
# could echo a line into, exactly as `git push --no-verify` is one flag away —
# the trust class the header states for the full ledger, unchanged and no weaker
# here. What follows from that is the fail-closed direction: a malformed key is
# a MISS on read and a REFUSAL on write; a row tagged with a schema this build
# does not know is not a hit; no ledger file is a miss; every doubt re-measures.
# The consult path NEVER exits 2 — a broken cache must cost a re-run, never a
# gate.

#: Bumped when the key's INPUTS change shape. A row tagged with anything else is
#: not a hit — a verdict from a future build is a verdict about a question this
#: build cannot ask.
LOOP_LEDGER_SCHEMA=loop-v1

#: The last fingerprint `loop_env_fingerprint` composed, and its five components
#: SPELLED OUT rather than only hashed. A miss on the environment line is the
#: one miss a reader cannot diagnose from the key alone — the key is a digest of
#: a digest — so the components are printed beside it and two banners put side
#: by side name which of the five moved. Set by `loop_env_fingerprint`; empty
#: until it has run, and empty is honest rather than stale.
LOOP_ENV_FINGERPRINT=""
LOOP_ENV_COMPONENTS=""

#: The five components, in the ONE fixed order every writer and every reader
#: here uses: `loop_env_fingerprint` composes them in it, `loop_ledger_record`
#: appends them in it, and `loop_ledger_attribute` names them in it when more
#: than one moved. Typed once so a sixth component is added in one place.
LOOP_ENV_COMPONENT_FIELDS='env-file excluded dists env-reads head merge-base'

#: The two of those five that are REVISION coordinates rather than inputs the
#: suite stands on. They are why the attributor had to grow: they ride inside
#: the env digest, so a docs-only commit on main moves `tree=` AND `env=`
#: together and every arm of the old three-line logic fell through to
#: `unmatched` — measured from the field on 2026-09-07, on a verifier's clone of
#: a banked branch, where env-file, excluded and dists were all equal. A tree
#: that moved WITH ONLY THESE TWO is a tree that moved; a tree that moved
#: alongside one of the other three is two things moving and neither vouches.
LOOP_ENV_REV_FIELDS='head merge-base'

# `DJB_LOOP_LEDGER` points these at a scratch file, which is how the drive
# forges rows — a stale one, a future-schema one, a corrupt one — without the
# forge ever being able to become a banked verdict in the real checkout. The
# same seam `DJB_PARTITION_LEDGER` is for the partition's rows, and for the same
# reason: a drive that wrote into the real common git dir would be planting
# verdicts in the tree it is testing.
loop_ledger_path() {
    if [ -n "${DJB_LOOP_LEDGER:-}" ]; then
        printf '%s\n' "$DJB_LOOP_LEDGER"
        return 0
    fi
    gate_local_path djb-loop-verdicts
}

#: The sentinels a DERIVER puts beside itself to declare which `.env` keys it
#: writes per checkout. Read by `loop_env_fingerprint` below.
LOOP_ENV_DECL_BEGIN='# >>> derived-env-keys >>>'
LOOP_ENV_DECL_END='# <<< derived-env-keys <<<'

# loop_env_derived_keys — every key name declared by a deriver, one per line,
# sorted and deduped, on stdout. Empty output means NO DECLARATION WAS FOUND.
#
# THE DECLARATION LIVES BESIDE THE DERIVER, never in a list here. `scripts/db.sh`
# derives `DATABASE_NAME` per checkout (CLAUDE.md's own escape clause names it),
# `scripts/rung_start.sh` derives this checkout's bucket. A list in this file
# would be right on the day it was written; a sentinel block is edited by the
# person changing the derivation, in the file they already have open.
#
# THE ENTRY FORM IS `# <KEY> — <reason>` AND THE EM DASH IS LOAD-BEARING. Without
# it every continuation line that happens to start with an upper-case word is a
# key: the first draft of this parser read `WHERE` out of the prose sentence "A
# property of WHERE this tree is" and would have excluded a `.env` line called
# `WHERE` from the hash for ever. A declaration format that a paragraph can
# accidentally satisfy is not a declaration.
loop_env_derived_keys() {
    local f
    for f in scripts/*.sh; do
        [ -f "$f" ] || continue
        awk -v b="$LOOP_ENV_DECL_BEGIN" -v e="$LOOP_ENV_DECL_END" -v dash="—" '
            index($0, b) { on = 1; next }
            index($0, e) { on = 0; next }
            on {
                line = $0
                sub(/^[ \t]*#[ \t]*/, "", line)
                if (line !~ /^[A-Z][A-Z0-9_]*[ \t]/) next
                name = line
                sub(/[ \t].*$/, "", name)
                rest = substr(line, length(name) + 1)
                sub(/^[ \t]+/, "", rest)
                if (substr(rest, 1, length(dash)) != dash) next
                print name
            }
        ' "$f"
    done | sort -u
}

#: WHO OWNS "what the suite reads from the environment". Not this file, and
#: deliberately: `quality/partition.py::suite_environment_names()` derives the
#: names from `config/settings/**` by AST and subtracts `config/settings/test.py`'s
#: pins and the lockfile's tolerated harness knobs, and the FULL gate's
#: `bent_environment()` already stands on exactly that census. A second list of
#: names here would be right on the day it was typed and silent the day a
#: setting was added — which is one level out from the defect that bought this
#: (R3's F2): the full gate had a check for this class and the loop had none.
LOOP_ENV_READS_OWNER='quality/partition.py'

#: `DJB_LOOP_ENV_READS` — a file of names, one per line, exactly as the owner
#: would print them. THE DRIVES' SEAM, the same pattern and the same disposition
#: as `DJB_LOOP_LEDGER` above: a scratch checkout carries no `quality/` tree, so
#: without it no case could drive the value folding at all. It is a cache seam
#: and not a boundary — this whole ledger is a cache and never a security
#: boundary, which `scripts/tests/test_loop_ledger.sh` states in its own header.

# loop_env_reads — a digest of the EFFECTIVE value of every name the suite reads
# from the environment, on stdout, or the literal `no-census`.
# Exit 0 derived · 1 could not look.
#
# EFFECTIVE MEANS `read_env(overwrite=False)`'s OWN PRECEDENCE: the process
# environment first, the `.env` file only where the process has nothing. That is
# `config/settings/base.py`'s call and it SETDEFAULTS, so an exported name wins
# over the file and an exported EMPTY name wins too — which is why an unset name
# is spelled `<unset>` here rather than as an empty value. The blindness this
# closes is exactly that: the fingerprint hashed the `.env` FILE, so the
# disabled-apps knob exported in the process environment left the key
# byte-identical and a narrower green was reusable as a full one.
#
# AND NO NAME THE CENSUS RETURNS IS SPELLED IN THIS FILE, comments included —
# the drive asserts it, deriving the population from the owner. A prose mention
# is a second list with extra steps: it reads as authoritative, nothing keeps it
# in step, and the census is the only thing here entitled to name a variable.
#
# THE THREE ANSWERS, and each is a different thing:
#
#   * a digest — the census was read and folded.
#   * `no-census` — this checkout has no `quality/partition.py`. It is NOT this
#     tree (every drive's scratch checkout is such a place), and a named absence
#     that every such checkout shares is deterministic, which a refusal is not.
#     On the real tree the owner is tracked and in the partition's own closure,
#     so it cannot go missing quietly.
#   * exit 1 — the owner is HERE and could not be read. A read that did not
#     answer is never an empty answer: no key is derived and nothing is reused,
#     the same disposition the distribution census takes below.
loop_env_reads() {
    local names python env_file digest
    if [ -n "${DJB_LOOP_ENV_READS:-}" ]; then
        [ -f "$DJB_LOOP_ENV_READS" ] || return 1
        names=$(cat "$DJB_LOOP_ENV_READS") || return 1
    elif [ -f "$LOOP_ENV_READS_OWNER" ]; then
        # THE CHECKOUT'S OWN INTERPRETER, named rather than searched. `uv run`
        # would resolve and possibly install on a path that must stay cheap and
        # must never write; `python3` off PATH is some other environment's, and
        # the owner needs this one's PyYAML. The venv is already a hard
        # requirement two blocks down, where zero distributions is could-not-look.
        python=.venv/bin/python
        [ -x "$python" ] || return 1
        names=$("$python" -m quality.partition env-reads 2>/dev/null) || return 1
    else
        printf 'no-census\n'
        return 0
    fi
    # An empty census is a read that did not answer. The owner refuses to print
    # one; a seam file that is empty is the same claim and gets the same answer.
    [ -n "$names" ] || return 1

    env_file=.env
    [ -f "$env_file" ] || env_file=/dev/null
    digest=$(DJB_LOOP_READ_NAMES="$names" awk '
        BEGIN { n = split(ENVIRON["DJB_LOOP_READ_NAMES"], want, "\n") }
        {
            line = $0
            sub(/^[ \t]+/, "", line)
            if (line ~ /^#/) next
            if (line !~ /=/) next
            name = line
            sub(/=.*$/, "", name)
            gsub(/[ \t]/, "", name)
            value = line
            sub(/^[^=]*=/, "", value)
            sub(/^[ \t]+/, "", value)
            sub(/[ \t]+$/, "", value)
            # One layer of matching quotes, which is `partition.py::_dotenv`s
            # own narrowing of `django-environ`s read. \047 is a single quote:
            # this program is inside single quotes and cannot contain one.
            q = substr(value, 1, 1)
            if ((q == "\"" || q == "\047") && length(value) > 1 &&
                substr(value, length(value), 1) == q) {
                value = substr(value, 2, length(value) - 2)
            }
            file[name] = value
            seen[name] = 1
        }
        END {
            for (i = 1; i <= n; i++) {
                name = want[i]
                if (name == "") continue
                # `in ENVIRON` and not a truth test: an exported EMPTY value is
                # SET, it wins over the file exactly as a non-empty one does,
                # and reading it as absent would hide the one case where a name
                # being present at all is the whole difference.
                if (name in ENVIRON) print name "=" ENVIRON[name]
                else if (name in seen) print name "=" file[name]
                else print name "=<unset>"
            }
        }
    ' "$env_file" | sha256_of) || return 1
    [ -n "$digest" ] || return 1
    printf '%s\n' "$digest"
}

# loop_env_fingerprint — one digest of everything the suite stands on that the
# tree hash does not carry, on stdout. Exit 0 derived · 1 could not look.
#
# FIVE INPUTS:
#
#   * `.env`, MINUS the deriver-declared keys. Those keys are derived FROM the
#     checkout — `DATABASE_NAME` is a hash of this checkout's own path — so
#     including them would key every verdict to one directory and no verdict
#     would ever be reused anywhere. Excluding an UNDECLARED key would be worse:
#     it would let a verdict earned under one configuration vouch for another.
#   * ZERO DISCOVERABLE DECLARATIONS IS A BROKEN READ, NOT AN EMPTY ANSWER.
#     If no deriver declares anything, the sentinel convention is gone or this
#     is not that tree, and the honest answer is to hash the WHOLE file — which
#     puts the per-checkout derived values back into the key and makes every
#     cross-checkout reuse a miss. A miss costs a re-run; a hit on an exclusion
#     nobody could verify costs a verdict about the wrong configuration.
#   * The installed-distribution census. A dependency change moves the suite
#     without moving a tracked file (`.venv` is ignored). Zero distributions is
#     could-not-look, not an empty venv.
#   * THE EFFECTIVE ENVIRONMENT READ-SET — `loop_env_reads` above, added by R3's
#     F2x. The `.env` digest is the FILE, and the file is not what the suite
#     stands on: `read_env(overwrite=False)` lets an exported name win over it,
#     so a key that hashed only the file was blind to every variable a terminal
#     exported. This is the component that is neither the file nor the tree.
#   * HEAD, and the MERGE-BASE with `refs/heads/main` — see the header.
loop_env_fingerprint() {
    local env_file=.env keys excluded dists head base venv site env_digest reads
    keys=$(loop_env_derived_keys)
    if [ -f "$env_file" ]; then
        if [ -z "$keys" ]; then
            excluded="UNDECLARED(whole-file)"
            env_digest=$(sha256_of "$env_file") || return 1
        else
            excluded=$(printf '%s' "$keys" | tr '\n' ',')
            # THROUGH THE ENVIRONMENT, NOT `-v`. awk processes escape sequences
            # in a `-v` assignment and cannot take a literal newline in one:
            # `awk -v keys="$keys"` with a multi-key list dies "newline in
            # string" on stderr, splits nothing, drops nothing, and STILL
            # returns a digest — a silent whole-file hash wearing an exclusion
            # list's name. Measured on the first draft of this function.
            env_digest=$(DJB_LOOP_ENV_KEYS="$keys" awk '
                BEGIN {
                    n = split(ENVIRON["DJB_LOOP_ENV_KEYS"], k, "\n")
                    for (i = 1; i <= n; i++) if (k[i] != "") drop[k[i]] = 1
                }
                {
                    line = $0
                    name = line
                    sub(/=.*$/, "", name)
                    gsub(/[ \t]/, "", name)
                    if (name in drop) next
                    print line
                }
            ' "$env_file" | sha256_of) || return 1
        fi
    else
        excluded="no-env-file"
        env_digest="no-env-file"
    fi

    venv=.venv
    site=""
    if [ -d "$venv" ]; then
        site=$(find "$venv" -maxdepth 4 -type d -name '*.dist-info' 2>/dev/null | sed 's:.*/::' | sort)
    fi
    if [ -z "$site" ]; then
        echo "!! the --loop ledger could not census the installed distributions under" >&2
        echo "   ${venv}. Zero distributions is a read that did not answer, not an" >&2
        echo "   empty environment — no key is derived and nothing is reused." >&2
        return 1
    fi
    dists=$(printf '%s' "$site" | sha256_of) || return 1

    reads=$(loop_env_reads) || {
        echo "!! the --loop ledger could not read this checkout's environment read-set" >&2
        echo "   through ${LOOP_ENV_READS_OWNER}. A census that did not answer is not an" >&2
        echo "   empty environment — no key is derived and nothing is reused." >&2
        return 1
    }

    head=$(git rev-parse -q --verify HEAD 2>/dev/null || printf 'unborn')
    base="no-local-main"
    if git rev-parse -q --verify refs/heads/main >/dev/null 2>&1; then
        base=$(git merge-base HEAD refs/heads/main 2>/dev/null || printf 'no-merge-base')
    fi

    # THE COMPONENTS, KEPT FOR PRINTING — and the hashed line below is NOT
    # rebuilt from them. The composition that feeds `sha256_of` is spelled
    # separately from the printable one, whose field names are the ones the miss
    # banner and the criteria use (`env-file=` for the .env digest, which the
    # hashed line calls `env=` and which is NOT the whole fingerprint).
    #
    # THE HASHED LINE GREW A FIELD AT R3's F2x, AND THAT COST EVERY BANKED ROW
    # IN EVERY CHECKOUT ONE RE-MEASURE — deliberately, once, and said out loud
    # here because the note that used to stand in this place said the
    # composition was byte-identical FOR THAT REASON. It is the right direction:
    # a fingerprint that will not move is a fingerprint nobody can fix, and the
    # rows it invalidated are precisely the rows that could not say what
    # environment they were earned under. `reads=` goes where its input belongs,
    # beside the other things the suite stands on and before the two revision
    # coordinates, which `LOOP_ENV_REV_FIELDS` keeps at the end.
    LOOP_ENV_COMPONENTS=$(printf 'env-file=%s excluded=%s dists=%s env-reads=%s head=%s merge-base=%s' \
        "$env_digest" "$excluded" "$dists" "$reads" "$head" "$base")
    LOOP_ENV_FINGERPRINT=$(printf 'env=%s excluded=%s dists=%s reads=%s head=%s merge-base=%s\n' \
        "$env_digest" "$excluded" "$dists" "$reads" "$head" "$base" |
        sha256_of)
    [ -n "$LOOP_ENV_FINGERPRINT" ] || return 1
    printf '%s\n' "$LOOP_ENV_FINGERPRINT"
}

# loop_env_sync — bring `.venv` to the lockfile BEFORE the key is derived, and
# say on stdout what that cost. Exit 0 always.
#
# THE DEFECT IT CLOSES, measured on three verifier boxes on 2026-09-18. The
# fingerprint above censuses the installed distributions, because a dependency
# change moves the suite without moving a tracked file. The gate's own first
# `uv run` SYNCS: on a box whose image was baked before a package joined
# `uv.lock`, the first leg installed it, the distribution census moved between
# the start key and the end key, and a completely green `--loop` refused to bank
# — three times, on three trees, each time reading as "something moved while the
# gate ran" with a clean `git status` beside it. The install was not a race; it
# was the gate's own first leg doing the thing the key was watching for.
#
# SO THE SYNC MOVES AHEAD OF THE KEY. After this call the environment the legs
# run in is the environment the key names, which is the property the `dists=`
# component exists to assert. It is the FIRST `uv run`'s work done under a name,
# at a moment where it is free to move the census, rather than the same work
# done anonymously one leg later where it is not.
#
# `--frozen`, AND THE REASON IS `scripts/verify_start.sh`'s VERBATIM: a bare
# `uv sync` may RE-LOCK and rewrite `uv.lock`, a TRACKED file — which would move
# the OTHER half of the key at the very moment this function exists to hold both
# halves still. `--frozen` installs the lockfile as it stands and touches
# nothing tracked.
#
# IT NEVER REFUSES, and that is a disposition rather than an oversight. This is
# preparation for a CACHE key, not an instrument: a checkout with no `uv`, no
# lockfile or a lockfile that will not install is a checkout whose legs are
# about to say so in their own words, with their own exit status. Refusing here
# would replace a leg's real red with a ledger's exit 2 and tell the reader
# about the cache instead of about their tree. What it does instead is PRINT —
# every line below names what happened, so a run that banks nothing can still be
# read backwards.
#
#: `DJB_LOOP_NO_SYNC` — skip it. The seam the drives use (a scratch checkout has
#: no lockfile to install), and the escape for a builder who is deliberately
#: standing on an environment the lockfile does not describe. It is printed, and
#: the line says what the skip costs.
loop_env_sync() {
    local out t0 took rc=0 summary reverted=0
    if [ -n "${DJB_LOOP_NO_SYNC:-}" ]; then
        echo "  environment: NOT synced — DJB_LOOP_NO_SYNC is set. Whatever the first \`uv run\`"
        echo "               installs will move this key's env half, and a green run then banks"
        echo "               nothing."
        return 0
    fi
    if ! command -v uv >/dev/null 2>&1; then
        echo "  environment: NOT synced — no \`uv\` on PATH, so nothing here can install the"
        echo "               lockfile. The legs below will say so in their own words."
        return 0
    fi
    out=$(mktemp "${TMPDIR:-/tmp}/djb-loop-sync.XXXXXX") || {
        echo "  environment: NOT synced — no scratch file under ${TMPDIR:-/tmp} to read uv's"
        echo "               answer out of."
        return 0
    }
    t0=$(date +%s)
    uv sync --frozen >"$out" 2>&1 || rc=$?
    took=$(($(date +%s) - t0))
    if [ "$rc" != 0 ]; then
        echo "  environment: \`uv sync --frozen\` exited ${rc} after ${took}s — the environment is"
        echo "               whatever it already was, and this run's env key may move under it."
        sed 's/^/               /' "$out"
        rm -f "$out"
        return 0
    fi
    # UV'S OWN SUMMARY, READ OUT OF THE FILE — never a second census of our own,
    # so there is one answer to "what changed here" and it belongs to the tool
    # that did it. `Installed`/`Uninstalled`/`Prepared` are the lines that would
    # have moved the distribution census a leg later, and the no-op line is
    # uv's too (`Checked <n> packages in <t>` on the version this box runs,
    # `Audited …` on older ones). THE LAST LINE IS THE FALLBACK rather than a
    # sentence of ours: uv has renamed that summary before and will again, and
    # "uv printed no summary line" would then read as a defect in this function
    # when the truth is that uv said something we did not have a word for.
    # ONE LINE, JOINED IN awk rather than by a pipeline: this whole banner is
    # one line per fact and a multi-line value spliced into it would break the
    # shape every other line in the block keeps.
    summary=$(awk '
        /^(Installed|Uninstalled|Prepared|Audited|Checked|Resolved) / {
            s = (s == "" ? $0 : s "; " $0)
        }
        NF { last = $0 }
        END { print (s == "" ? last : s) }
    ' "$out")
    # AND IF IT TOOK SOMETHING OUT, THE LINE SAYS SO AND NAMES THE VALVE.
    # `uv sync` makes the venv MATCH the lockfile, so a builder standing on a
    # hand-patched environment — a debugger, a pinned fork, a wheel built by
    # hand — has it reverted here, silently, by a step whose whole purpose is
    # to be invisible. The one case where this function takes something away
    # from a person is the one case it owes them a sentence, and the sentence
    # has to name the way out or it is only an apology.
    #
    # ON A FILE AND NOT AT A PIPELINE TAIL: `grep -q` here reads `$out`
    # directly, so there is no producer for it to close a pipe under — the
    # GQ-1 hazard is the `producer | grep -q` form, which this is not.
    if grep -q '^Uninstalled ' "$out" 2>/dev/null; then
        reverted=1
    fi
    rm -f "$out"
    echo "  environment: uv sync --frozen, ${took}s — ${summary:-uv printed nothing at all}"
    if [ "$reverted" = 1 ]; then
        echo "               UNINSTALLED: this venv held a distribution the lockfile does not"
        echo "               name, and the sync took it out. DJB_LOOP_NO_SYNC=1 keeps a"
        echo "               hand-patched environment — at the price this function exists to"
        echo "               remove, which is the key's env half moving under the run."
    fi
    echo "               (ahead of the key, so the distribution census the key carries is the"
    echo "               one the legs run in — loop_env_sync, scripts/gate_ledger.sh)"
}

#: `loop-v1:<64 hex>` and nothing else.
LOOP_KEY_RE='^loop-v1:[0-9a-f]{64}$'

# loop_ledger_key <measured tree> <canonical scope> — the key on stdout.
# Exit 0 derived · 1 could not look (which every caller turns into "no reuse and
# no record", never into a gate verdict).
loop_ledger_key() {
    local tree=$1 scope=$2 fingerprint digest
    [ -n "$tree" ] || return 1
    [ -n "$scope" ] || return 1
    # An always-on declaration nobody could read must never become a hit. It
    # still produces a key — a non-deterministic one would be worse — and the
    # RECORD path below refuses it, so no row carrying it can ever exist.
    fingerprint=$(loop_env_fingerprint) || return 1
    digest=$(printf 'tree=%s\nenv=%s\nscope=%s\n' "$tree" "$fingerprint" "$scope" |
        sha256_of)
    [ -n "$digest" ] || return 1
    printf '%s:%s\n' "$LOOP_LEDGER_SCHEMA" "$digest"
}

# loop_key_moved <tree0> <env0> <parts0> <tree1> <env1> <parts1> <scope>
#
# WHICH THIRD OF THE KEY MOVED WHILE THE GATE RAN, one line per moved half and
# one per moved fingerprint component, on stdout. Exit 0 always: this is a
# printer for a refusal that has already been decided, never a second verdict.
#
# WHY IT EXISTS. The end-of-run re-derivation refused with one sentence —
# "something moved while the gate ran" — and a builder reading it has a whole
# `--loop` to re-spend and no subject to fix. The key is a digest of three
# inputs and cannot be read backwards, so the only place the answer can be
# assembled is here, where both ends' inputs are still in hand. This is the
# `loop_miss_narrative` discipline (name the component that moved) applied to
# the OTHER end of the same run.
#
# THE SCOPE IS PASSED AND NOT COMPARED, and that is a statement rather than an
# omission: both derivations read the same `LOOP_SCOPE_CANONICAL`, derived once
# before the first leg, so the scope CANNOT differ between them. Printing it
# keeps the third input visible to a reader who is checking that claim.
loop_key_moved() {
    local tree0=$1 env0=$2 parts0=$3 tree1=$4 env1=$5 parts1=$6 scope=$7
    if [ "$tree0" != "$tree1" ]; then
        echo "  moved: THE TREE — a file the gate can read was written, removed or"
        echo "         changed while the gate ran (\`git add -A\`, so .gitignore applies)."
        echo "         start tree ${tree0}"
        echo "         end   tree ${tree1}"
    fi
    if [ "$env0" != "$env1" ]; then
        echo "  moved: THE ENVIRONMENT — start ${env0}"
        echo "                           end   ${env1}"
        # FIELD BY FIELD, positionally. Both strings are composed by one
        # `printf` in `loop_env_fingerprint`, so field k is the same field on
        # both sides and no value it holds contains a space.
        DJB_KEY_PARTS0="$parts0" DJB_KEY_PARTS1="$parts1" awk '
            BEGIN {
                a = split(ENVIRON["DJB_KEY_PARTS0"], A, " ")
                b = split(ENVIRON["DJB_KEY_PARTS1"], B, " ")
                n = (a > b) ? a : b
                for (i = 1; i <= n; i++) {
                    if (A[i] == B[i]) continue
                    name = A[i]; sub(/=.*$/, "", name)
                    if (name == "") { name = B[i]; sub(/=.*$/, "", name) }
                    printf("         %s: %s -> %s\n", name,
                           (A[i] == "" ? "<absent>" : A[i]),
                           (B[i] == "" ? "<absent>" : B[i]))
                }
            }
        '
    fi
    if [ "$tree0" = "$tree1" ] && [ "$env0" = "$env1" ]; then
        # NEITHER HALF MOVED AND THE KEYS STILL DIFFER. That is the key
        # derivation disagreeing with itself, which is a defect in this file
        # rather than a tree that changed — and it must not read as one.
        echo "  moved: NEITHER the tree nor the environment — the two keys differ over"
        echo "         identical inputs, which is a defect in the key derivation itself."
    fi
    echo "  scope (identical by construction — derived once, before the first leg):"
    echo "         ${scope}"
}

# loop_ledger_record <key> <scope> [<passes>] — one line, appended, schema first.
#
# `passes=` GOES LAST, and that placement is the whole of its design. A verdict
# row that does not say WHAT RAN is a row nobody can audit later: "green" means
# one pass here and two at the full gate, and the day either changes, every
# older row silently starts meaning something else. Appending keeps every
# pre-existing line parsing exactly as it did — the same precedent `sanction=`
# set on the full row above — so the schema tag stays `loop-v1`.
#
# WHY IT IS 1 AND NOT 2, recorded rather than assumed. The local `--loop` runs
# ONE pytest pass (`scripts/test.sh` ends in a single `uv run pytest`, and
# `scripts/check.sh`'s two `--loop` call sites are the arms of one `if`). The
# full gate's `pytest-x2` runs two under one seed, which is the partition bank's
# two-green-passes doctrine and is untouched by any of this. The two tiers make
# different claims and now say which.
#
# AND `passes=1` ON A REUSE ROW IS THE SAME LITERAL AS ON A MEASURED ONE, which
# is a thing to read carefully rather than a defect to fix. A row banked by the
# docs-only pytest reuse carries `passes=1` because the pass it rests on was one
# pass — but THIS run ran none, and the field cannot say that. The distinction
# lives in `reuse=`, and it is a property of the TRAIL and not of this field: a
# reuse row may rest on another reuse row, so "what actually measured these
# bytes" is found by walking `reuse=` to the first row that has none. A reader
# counting `passes=` across rows is counting claims, never pytest invocations.
loop_ledger_record() {
    local key=$1 scope=$2 passes=${3:-1} tree=${4:-} env=${5:-} reuse=${6:-} path
    printf '%s' "$key" | grep -E "$LOOP_KEY_RE" >/dev/null || {
        echo "loop_ledger_record: '$key' is not a loop key — nothing recorded" >&2
        return 2
    }
    # The refusal that keeps an unverifiable always-on read out of the ledger.
    case "$scope" in
    *UNDECLARED*)
        echo "loop_ledger_record: the always-on declaration could not be read" >&2
        echo "  (apps/conftest.py's sentinel block). A verdict whose SELECTION rules" >&2
        echo "  nobody could digest is not a verdict about a selection — nothing" >&2
        echo "  recorded, and every later run re-measures." >&2
        return 2
        ;;
    esac
    path=$(loop_ledger_path) || return 1
    # `tree=` AND `env=` GO AFTER `passes=`, for the reason `passes=` itself
    # went after `scope=`: appending leaves every pre-existing line parsing
    # exactly as it did, so a row written before this field existed is still a
    # readable row and still a legal hit. They are the two key inputs a reader
    # cannot recover from the key — the key is a digest OF them — and without
    # them a miss can only be reported as "no row", which tells the next
    # verifier nothing about WHY the bank missed.
    #
    # AND THE FIVE COMPONENTS GO AFTER `env=`, BY THE SAME PRECEDENT AGAIN —
    # `passes=` after `scope=`, then `tree=`/`env=` after `passes=`, now the
    # components after `env=`. Appending is what keeps every row written before
    # this change a legal, readable, HITTING row: the key is the match, the
    # tail is only ever read on a MISS.
    #
    # THEY COME FROM THE GLOBAL, IN THE CALLER'S SHELL, AND NOT FROM A SIXTH
    # PARAMETER. `LOOP_ENV_COMPONENTS` is set by `loop_env_fingerprint`, which
    # every caller must already have run PLAINLY rather than inside `$(...)` —
    # a substitution's copy of the global dies with the subshell, which is
    # exactly how the row once banked `env=unstated` and went green. Reading the
    # global here means the components can never disagree with the `env=` digest
    # beside them: they are the same composition, from the same call.
    #
    # EMPTY IS HONEST. A caller that never derived a fingerprint appends
    # nothing, and the row it writes is a row without components — which the
    # attributor recognises and says so, rather than comparing against empty
    # strings and calling that a difference.
    #
    # AND `waited=`/`took=` GO AFTER THE COMPONENTS, by the precedent that is by
    # now the only rule this row has ever followed: append, never insert. The
    # full row above gained the same two fields in the same commit and for the
    # same reason — a verdict that says what it measured and never what it cost
    # cannot answer "is the gate slow or is the box busy", which is the question
    # every builder waiting on one actually has. `gate_ledger_cost_fields` is
    # shared with the full row so the two can never disagree about the arithmetic.
    #
    # AND `reuse=` GOES AFTER THOSE, by the same precedent one more time, and it
    # is the field that makes property 2 true of this tier: A REUSE IS RECORDED
    # AS A REUSE, NEVER AS A MEASUREMENT. A docs-only reuse banks a row keyed on
    # THIS tree — so it is itself reusable, which is the point — and the field
    # names the banked tree whose pytest verdict it rests on, so a reader
    # following a chain of reuses reaches the measurement at the end of it.
    # Nothing limits that chain's length; the row says what it stands on and the
    # readouts reader can walk it.
    #
    # THE THIRD FIELD STAYS THE LITERAL `loop`, and that is not decoration:
    # `scripts/verify_start.sh`'s LOOP SEED matches `^loop-v1 loop-v1:<64> loop `
    # before it copies a row into a verifier's clone, so a reuse row spelled
    # into that position would be a row no verifier could ever inherit.
    local components="${LOOP_ENV_COMPONENTS:-}"
    printf '%s %s loop %s caller=%s scope=%s passes=%s tree=%s env=%s%s%s%s\n' \
        "$LOOP_LEDGER_SCHEMA" "$key" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(gate_caller)" \
        "$(printf '%s' "$scope" | tr '\n ' '__')" "$passes" \
        "${tree:-unstated}" "${env:-unstated}" \
        "${components:+ $components}" "$(gate_ledger_cost_fields)" \
        "${reuse:+ reuse=$reuse}" >>"$path"
}

# loop_component_value <fields line> <name> — the value of ` <name>=<v>` on
# stdout, empty when the field is absent. Space-delimited, first match, no
# subprocess: this runs once per field per row per consult.
#
# THE LEADING SPACE IS WHAT TELLS `env=` AND `env-file=` APART, and it is the
# same reason `loop_ledger_attribute` pads every row with a trailing one: a
# field name is a name only when a space precedes it.
loop_component_value() {
    local line=" $1 " name=$2 rest
    case "$line" in
    *" ${name}="*) ;;
    *) return 0 ;;
    esac
    rest=${line#*" ${name}="}
    printf '%s' "${rest%% *}"
}

# loop_components_malformed <fields line> — the first field that is missing or
# the wrong shape, on stdout; EMPTY when all five read cleanly. Exit 0 always.
#
# WHAT THIS IS AND IS NOT. It is not a defence against a forged row — the trust
# class above says a local file an agent could echo a line into is a cache and
# never a boundary, and a hand-edited row that is well FORMED attributes on what
# it says. It is the read that keeps a row nobody can parse from being compared
# field-by-field against empty strings and reported as five components moving.
# A row that cannot be read is `unmatched`, and the attributor names the field.
loop_components_malformed() {
    local line=$1 f v
    for f in $LOOP_ENV_COMPONENT_FIELDS; do
        v=$(loop_component_value "$line" "$f")
        if [ -z "$v" ]; then
            printf '%s (missing)' "$f"
            return 0
        fi
        case "$f" in
        env-file)
            # `no-env-file` is the DECLARED absence of a `.env`, which
            # `loop_env_fingerprint` writes on purpose. Not a malformation.
            if [ "$v" != "no-env-file" ]; then
                printf '%s' "$v" | grep -E '^[0-9a-f]{64}$' >/dev/null || {
                    printf '%s (not a digest)' "$f"
                    return 0
                }
            fi
            ;;
        dists)
            printf '%s' "$v" | grep -E '^[0-9a-f]{64}$' >/dev/null || {
                printf '%s (not a digest)' "$f"
                return 0
            }
            ;;
        env-reads)
            # `no-census` is the DECLARED absence of `quality/partition.py`,
            # which `loop_env_reads` writes on purpose for a checkout that is
            # not this tree. Not a malformation, on `env-file`'s own precedent.
            if [ "$v" != "no-census" ]; then
                printf '%s' "$v" | grep -E '^[0-9a-f]{64}$' >/dev/null || {
                    printf '%s (not a digest)' "$f"
                    return 0
                }
            fi
            ;;
        esac
    done
    return 0
}

# loop_ledger_census — "<rows> rows (<seeded> seeded from <source>)" on stdout,
# for the banner. A clone seeded by `verify_start.sh` carries a note beside the
# ledger saying how many rows it arrived with and where from; without that note
# the seeded count is 0 and the sentence says so rather than guessing.
loop_ledger_census() {
    local path rows note seeded source
    path=$(loop_ledger_path) || return 1
    # `grep -c` PRINTS the count and EXITS 1 when the count is zero, so a
    # `|| printf '0'` fallback appends a second zero and the census reads "0 0".
    # Measured on the first draft of this function. The status is what the
    # fallback must catch, never the output.
    rows=0
    if [ -f "$path" ]; then
        rows=$(grep -c "^$LOOP_LEDGER_SCHEMA " "$path" 2>/dev/null) || rows=0
    fi
    note="${path}-seed"
    if [ -f "$note" ]; then
        seeded=$(sed -n 's/^seeded=\([0-9][0-9]*\).*/\1/p' "$note" | tail -1)
        source=$(sed -n 's/^.*from=\(.*\)$/\1/p' "$note" | tail -1)
        printf '%s rows (%s seeded from %s)\n' "$rows" "${seeded:-0}" "${source:-an unnamed source}"
    else
        printf '%s rows (0 seeded — this ledger was not seeded from a source)\n' "$rows"
    fi
}

# loop_attribute_head_detail <banked head> — the `since banked head` line on
# stdout. Exit 0 always, whatever git says.
#
# WHAT MOVED, AND WHETHER IT WAS ONLY DOCS. A `tree` token says the bytes moved;
# this line says how many paths moved with them and whether all of them live
# under `docs/`. That answer is the counter a deferred piece of work is waiting
# on: a verifier's clone missing on a banked branch because main gained a
# ledger commit is a re-measure bought by a file no module under `apps/` names,
# and until this
#
# line existed nobody could count those without reading two banners by hand.
#
# `docs/` IS THE PREFIX TWO SHIPPED FILES ALREADY TREAT AS THE LEDGERS' HOME,
# cited rather than re-listed: `scripts/queue_cited.sh`'s SCOPE keeps
# `docs/product/` out of "the places a FIX lives", and `scripts/archaeology_lib.sh`
# classifies that tree as the buckets that never ship. It is a PATH PREFIX and
# never a semantic — a docs file some test read would be a false `yes`, declared
# here rather than discovered later.
#
# NOT DERIVABLE IS A NAMED ABSENCE, NEVER A GUESS. A row from another clone, a
# banked head that was amended away, an unborn HEAD: each says which it was.
loop_attribute_head_detail() {
    local h=$1 short files n docs p
    if [ -z "$h" ] || [ "$h" = "unborn" ]; then
        printf 'since banked head: not derivable (the row carries no usable head=)\n'
        return 0
    fi
    short=$(printf '%s' "$h" | cut -c1-8)
    if ! git rev-parse -q --verify "${h}^{commit}" >/dev/null 2>&1; then
        printf 'since banked head: not derivable (%s is not a commit in this repository)\n' "$short"
        return 0
    fi
    if ! git merge-base --is-ancestor "$h" HEAD >/dev/null 2>&1; then
        printf 'since banked head: not derivable (%s is not an ancestor of HEAD)\n' "$short"
        return 0
    fi
    files=$(git diff --name-only "$h" HEAD 2>/dev/null) || {
        printf 'since banked head: not derivable (git diff %s HEAD could not run)\n' "$short"
        return 0
    }
    n=0
    docs=yes
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        n=$((n + 1))
        case "$p" in
        docs/*) ;;
        *) docs=no ;;
        esac
    done <<EOF
$files
EOF
    if [ "$n" = "0" ]; then
        # NO COMMIT SINCE THE BANKED HEAD, so nothing was docs-only: the tree
        # moved in the WORKING TREE, which is a builder editing its own
        # checkout and is deliberately not the shape the counter counts.
        printf 'since banked head %s: 0 path(s) changed; docs-only: no (no commit since the banked head — the tree moved in the working tree)\n' "$short"
        return 0
    fi
    printf 'since banked head %s: %s path(s) changed; docs-only: %s\n' "$short" "$n" "$docs"
}

# loop_attribute_banked_line <row> — the banked row's own coordinates, shortened
# for reading, on stdout. The components line the banner already prints is THIS
# run's; a reader comparing them needs the other side, and reading it off a
# second banner was the manual step the token now replaces.
loop_attribute_banked_line() {
    local row=$1 out="" f v
    for f in $LOOP_ENV_COMPONENT_FIELDS; do
        v=$(loop_component_value "$row" "$f")
        case "$f" in
        env-file | dists) v=$(printf '%s' "$v" | cut -c1-12) ;;
        head | merge-base) v=$(printf '%s' "$v" | cut -c1-8) ;;
        esac
        out="${out}${out:+ }${f}=${v}"
    done
    printf 'banked row: tree=%s %s\n' \
        "$(loop_component_value "$row" tree | cut -c1-12)" "$out"
}

# loop_attribute_head_distance <banked head> — how many commits `HEAD` is ahead
# of that head, on stdout; EMPTY when this repository cannot place it. Exit 0
# always, whatever git says — it is on the consult path.
#
# EMPTY IS "NOT PLACEABLE", AND IT IS DELIBERATELY NOT ZERO. A row from another
# clone, a head amended away, an unborn HEAD and a head on a branch that never
# merged all answer empty, and `loop_attribute_nearer` ranks empty below every
# real distance — a row we can measure from is always the better row to name,
# whatever order the ledger happens to hold them in.
loop_attribute_head_distance() {
    local h=$1 n
    [ -n "$h" ] || return 0
    [ "$h" != "unborn" ] || return 0
    git rev-parse -q --verify "${h}^{commit}" >/dev/null 2>&1 || return 0
    git merge-base --is-ancestor "$h" HEAD >/dev/null 2>&1 || return 0
    n=$(git rev-list --count "${h}..HEAD" 2>/dev/null) || return 0
    case "$n" in
    '' | *[!0-9]*) return 0 ;;
    esac
    printf '%s' "$n"
}

# loop_attribute_nearer <candidate distance> <incumbent distance> <incumbent row>
# — exit 0 when the candidate should displace the incumbent. Used as an `if`
# condition, which is the one place `set -e` does not fire on a non-zero status.
#
# TIES GO TO THE CANDIDATE, which is what "ties → the last row in file order"
# means when the rows arrive in file order: the later row keeps replacing an
# equally-near earlier one. Rows are APPENDED, so the last of several equally
# near rows is the most recent verdict, and naming the most recent one is the
# behaviour a reader expects from a ledger.
loop_attribute_nearer() {
    local cand=$1 best=$2 bestrow=$3
    [ -n "$bestrow" ] || return 0
    if [ -z "$cand" ]; then
        # Not placeable: it can only displace another row that is not placeable
        # either, and then only because it is later in the file.
        [ -z "$best" ] && return 0
        return 1
    fi
    [ -n "$best" ] || return 0
    [ "$cand" -le "$best" ] || return 1
    return 0
}

# loop_ledger_attribute <tree> <env> <scope> — WHY the consult missed. LINE 1 IS
# THE TOKEN; every further line is detail. The tokens: `no-ledger` · `tree` ·
# `env:<component>[,<component>]` · `env` · `scope` · `unmatched`.
#
# IT NAMES THE COMPONENT NOW, BECAUSE THE ROW CARRIES ONE. The sentence that
# stood here said the opposite and was true when it was written: the row held
# only the env DIGEST, so the fingerprint's five parts were readable off two
# banners put side by side and nowhere else. `loop_ledger_record` now appends
# the five, so the comparison is the machine's. Described rather than re-spelled
# — a censused string counts wherever it appears, prose included.
#
# WHY IT MATTERS, and it is not tidiness. `head=` and `merge-base=` ride INSIDE
# the env digest, so ONE docs-only commit on main moves `tree=` and `env=`
# together; the old three-line logic needed one of them to hold still, found
# neither, and answered `unmatched` — in the commonest real case there is, a
# verifier's clone of a banked branch after the ledgers moved. Measured from the
# field on 2026-09-07. `unmatched` is now reserved for the case it describes:
# the tree moved AND something the suite actually stands on moved with it.
#
# MOST SPECIFIC FIRST, over rows of equal `scope=`, and the order is the one the
# criteria list:
#
#   * env-file, excluded and dists all EQUAL and the tree different → `tree`,
#     whatever the two revision components did — they moved with it, and the
#     detail line says what moved and whether it was only docs.
#   * the tree EQUAL and one or more components different → `env:<a>,<b>` in the
#     fixed field order. `env:head` and `env:merge-base` are an amend or a
#     rebase over an identical tree, named for the first time.
#   * the tree different AND a non-revision component different → `unmatched`,
#     honestly: two things moved and neither vouches for the other.
#   * a row with no components at all → the three-line logic below, untouched,
#     and the detail says the row predates the fields.
#
# CROSS-ROW PRECEDENCE, AND IT IS NOT A DETAIL: AN EQUAL-`tree` ROW ALWAYS
# OUTRANKS A DIFFERING-`tree` ROW. The four arms above describe ONE row; a
# `verify_start` clone is seeded with twenty-odd rows from other branches, so
# two different rows match two different arms in almost every real consult, and
# whichever the code looks at first is the answer the reader gets. Measured on
# 2026-09-08: the same inputs read `env:env-file` against the fixture's own row
# alone and `tree` against a clone's real 24 rows, because a FOREIGN row's tree
# arm was captured and returned before the clone's own equal-tree row was ever
# reached. So both arms are collected over EVERY row and the env arm is answered
# first — the run's own tree being banked is the more specific fact, and it is
# the one that keeps the reader from folding main and re-measuring for nothing.
#
# AND WITHIN ONE ARM, THE NEAREST BANKED HEAD WINS, never the first row in the
# file: among candidates the one whose `head=` is an ancestor of `HEAD` with the
# fewest commits behind it, a derivable head always beating a head this
# repository cannot place, ties going to the LAST row (the most recently
# appended). File order is an accident of which branch seeded the clone; the
# detail line's `since banked head` count is only worth reading if it was
# measured from the nearest row, which is what made the field's drift of one
# docs commit print `20 path(s) changed; docs-only: no`.
#
# The `no-ledger` and `scope` arms are the ones they always were.
#
# EXIT 0 ALWAYS, INCLUDING WHEN GIT REFUSES. An attributor that could fail would
# be a second way for a cache to break a gate, and every path above answers with
# a sentence rather than a status.
loop_ledger_attribute() {
    local tree=$1 env=$2 scope=$3 path rows canon
    path=$(loop_ledger_path) || {
        printf 'no-ledger\n'
        return 0
    }
    if [ ! -f "$path" ]; then
        printf 'no-ledger\n'
        return 0
    fi
    rows=$(grep -c "^$LOOP_LEDGER_SCHEMA " "$path" 2>/dev/null) || rows=0
    if [ "${rows:-0}" = "0" ]; then
        printf 'no-ledger\n'
        return 0
    fi
    canon=$(printf '%s' "$scope" | tr '\n ' '__')
    # EVERY FIELD IS MATCHED AS " name=value ", INCLUDING THE LAST ONE. `env=`
    # is at the end of the line, so a pattern with a trailing space never
    # matches it and every attribution silently came back `unmatched` — measured
    # on the first draft. Giving each line a trailing space makes one pattern
    # shape work for every field, which is cheaper than a special case that has
    # to move whenever a field is appended.
    local padded
    padded=$(sed 's/$/ /' "$path")

    # --- the component pass, over rows of equal scope that carry components ---
    #
    # IT RUNS ONLY WHEN THIS RUN'S OWN COMPONENTS READ CLEANLY. Comparing a
    # banked row against a fingerprint nobody could derive would name components
    # as "moved" on the strength of an empty string; the three-line logic below
    # is the honest answer in that case, and it is the answer this file gave
    # before the components existed at all.
    local mine="${LOOP_ENV_COMPONENTS:-}" mine_bad="" malformed="" nocomp=""
    if [ -n "$mine" ]; then
        mine_bad=$(loop_components_malformed "$mine")
    fi
    if [ -n "$mine" ] && [ -z "$mine_bad" ]; then
        local row bad rowtree diffs nonrev f mv rv rowdist
        local tree_row="" tree_dist="" env_row="" env_dist="" env_diffs=""
        while IFS= read -r row; do
            case "$row" in
            "$LOOP_LEDGER_SCHEMA "*) ;;
            *) continue ;;
            esac
            case "$row" in
            *" scope=${canon} "*) ;;
            *) continue ;;
            esac
            case "$row" in
            *" env-file="*) ;;
            *)
                nocomp=1
                continue
                ;;
            esac
            bad=$(loop_components_malformed "$row")
            if [ -n "$bad" ]; then
                [ -n "$malformed" ] || malformed="$bad"
                continue
            fi
            rowtree=$(loop_component_value "$row" tree)
            diffs=""
            nonrev=""
            for f in $LOOP_ENV_COMPONENT_FIELDS; do
                mv=$(loop_component_value "$mine" "$f")
                rv=$(loop_component_value "$row" "$f")
                if [ "$mv" != "$rv" ]; then
                    diffs="${diffs}${diffs:+,}${f}"
                    case " $LOOP_ENV_REV_FIELDS " in
                    *" $f "*) ;;
                    *) nonrev=1 ;;
                    esac
                fi
            done
            # THE DISTANCE IS DERIVED FOR EVERY CANDIDATE, EAGERLY, and the
            # cheaper lazy form was written first and thrown away: deferring it
            # until a second candidate arrives leaves the INCUMBENT's distance
            # unknown, and an unknown incumbent loses to any real distance — so
            # a far row planted second displaced a near row planted first, which
            # is the very bug this block exists to close. Three git calls per
            # candidate, once per gate consult; the census line prints the row
            # count, and the unindexed-ledger blind spot is declared with the
            # rung rather than paid for with a wrong answer.
            rowdist=$(loop_attribute_head_distance "$(loop_component_value "$row" head)")
            if [ "$rowtree" != "$tree" ]; then
                if [ -z "$nonrev" ] &&
                    loop_attribute_nearer "$rowdist" "$tree_dist" "$tree_row"; then
                    tree_row="$row"
                    tree_dist="$rowdist"
                fi
                continue
            fi
            if [ -n "$diffs" ] &&
                loop_attribute_nearer "$rowdist" "$env_dist" "$env_row"; then
                env_row="$row"
                env_dist="$rowdist"
                env_diffs="$diffs"
            fi
        done <<EOF
$padded
EOF
        # THE EQUAL-TREE ARM IS ANSWERED FIRST. This order IS the precedence
        # rule of 2026-09-08; swapping these two blocks is the defect the field
        # measured, and it is invisible against a one-row fixture.
        if [ -n "$env_row" ]; then
            printf 'env:%s\n' "$env_diffs"
            loop_attribute_banked_line "$env_row"
            return 0
        fi
        if [ -n "$tree_row" ]; then
            printf 'tree\n'
            loop_attribute_banked_line "$tree_row"
            loop_attribute_head_detail "$(loop_component_value "$tree_row" head)"
            # THE UNTRUNCATED COORDINATES, FOR A READER THAT IS A PROGRAM.
            # `banked row:` above is shortened for eyes (12 and 8 characters);
            # `loop_docs_only_reuse` below needs the WHOLE banked head to ask
            # git what moved since it, and the whole banked tree to name what a
            # reuse rests on. Emitting them here rather than re-finding the row
            # is what keeps ONE answer to "which row did the attributor pick":
            # a second search could pick a different one, and a reuse resting
            # on a row nobody attributed is a reuse nobody can audit.
            printf 'reuse-basis: head=%s tree=%s\n' \
                "$(loop_component_value "$tree_row" head)" \
                "$(loop_component_value "$tree_row" tree)"
            return 0
        fi
    fi

    # Most specific first: a row agreeing on two of the three lines names the
    # third as the difference. Two rows disagreeing in different ways is
    # possible and here the first match wins — the banner prints the inputs
    # beside this token, so a reader is never left with only the token.
    #
    # FILE ORDER IS THE RULE ON THIS PATH ONLY, and it is not the rule above.
    # These rows carry no components, so there is nothing to rank them by: no
    # `head=` to place against `HEAD`, no arm more specific than another. The
    # component pass above ranks its candidates (equal tree first, then nearest
    # banked head) precisely because the row gives it something to rank with.
    # A pre-ATTR-1 population is finite and shrinking; it is not worth a second
    # ordering rule, and the detail line says which path answered.
    #
    # THE FILTERS ARE THE ONES THEY ALWAYS WERE; what changed is that the match
    # is CAPTURED rather than discarded, so the detail line can say whether the
    # row that matched predates the components. `${var%%<newline>*}` takes the
    # first line WITHOUT a `| head -1`, which would close the pipe under its
    # producer for exactly the reason the note below gives.
    #
    # `grep PATTERN >/dev/null`, NEVER a trailing `| grep -q`. `-q` exits on the
    # first match and closes the pipe under its producer; a producer with more
    # than the 64KiB buffer still to write takes SIGPIPE and dies 141, and
    # `pipefail` hands 141 to the caller — a MATCH reported as a failure. A
    # ledger big enough to reach that is unlikely and "unlikely" is exactly the
    # argument that made it a bug the last two times (GQ-1's reproduction).
    local matched=""
    matched=$(printf '%s\n' "$padded" | grep -F " scope=${canon} " |
        grep -F " env=${env} " |
        grep -vF " tree=${tree} ") || matched=""
    if [ -n "$matched" ]; then
        printf 'tree\n'
        loop_attribute_row_detail "${matched%%$'\n'*}"
        return 0
    fi
    matched=$(printf '%s\n' "$padded" | grep -F " scope=${canon} " |
        grep -F " tree=${tree} ") || matched=""
    if [ -n "$matched" ]; then
        printf 'env\n'
        loop_attribute_row_detail "${matched%%$'\n'*}"
        return 0
    fi
    matched=$(printf '%s\n' "$padded" | grep -F " tree=${tree} " |
        grep -F " env=${env} ") || matched=""
    if [ -n "$matched" ]; then
        printf 'scope\n'
        return 0
    fi
    printf 'unmatched\n'
    if [ -n "$malformed" ]; then
        printf 'banked row unreadable: %s — nothing was compared against it\n' "$malformed"
    elif [ -n "$mine_bad" ]; then
        printf 'this run has no readable components: %s — the row could not be compared\n' "$mine_bad"
    elif [ -n "$nocomp" ]; then
        printf 'banked row carries no components (recorded before they were)\n'
    fi
    return 0
}

# loop_attribute_row_detail <row> — the detail line for a token derived from the
# THREE-LINE logic. Its only job is to say whether the row that matched predates
# the components, because that is the difference between "the machine compared
# five fields and this is what it found" and "the machine had three lines to go
# on, exactly as it always did".
loop_attribute_row_detail() {
    case "$1" in
    *" env-file="*) printf 'banked row carries components; this token came from the three-line match\n' ;;
    *) printf 'banked row carries no components (recorded before they were)\n' ;;
    esac
}

# ---- the docs-only reuse ----------------------------------------------------
#
# WHAT IT IS. A `--loop` that misses on `tree` ALONE, whose whole delta since
# the banked head is under `docs/`, is a run whose pytest pass would re-derive a
# result nothing in the delta can have changed. This says when the banked
# pytest verdict may stand in for that pass. Every other leg still runs: the
# `--fast` legs are ~30 s on this box and choosing which of them read docs is a
# hand list of an open set, where the saving is the 200-250 s pass.
#
# THE CACHE'S FOUR DECLARATIONS (principle 10), stated where the code is:
#   SOURCE OF TRUTH — the banked row the ATTRIBUTOR picked, and no other. The
#     row arrives through the attributor's `reuse-basis:` line rather than
#     through a second search of the ledger, so the reuse can never rest on a
#     row the banner did not name.
#   KEY SEMANTICS — unchanged. The reuse does not widen the key; it narrows the
#     WORK a miss on that key costs. The row it banks afterwards is keyed on
#     this tree exactly as a measured row is, and says what it rests on.
#   INVALIDATION — any non-`docs/` path in the delta, any uncommitted byte in
#     the working tree, any changed docs path spelled in a module under
#     `apps/`, an unreadable or absent basis: every one of them measures.
#   FAILURE BEHAVIOUR — fail closed and SILENT-ON-DOUBT. Exit 1 means measure;
#     there is no exit 2 on this path, for the reason the consult path has
#     none: a broken cache must cost a re-run, never a gate.
#
# IT IS CALLED PLAINLY, NEVER IN `$(...)`. It sets three globals, and a
# substitution's copy of a global dies with the subshell — the failure that once
# banked `env=unstated` and went green (the consult's own note, above).
#
# TWO THINGS IT DELIBERATELY DOES NOT DO, declared rather than discovered:
#   * It does not read a docs path by GLOB or by DIRECTORY. The population is
#     derived per changed path with `grep -rlF`, which is the criterion's own
#     spelling; a module that reads a docs DIRECTORY names no path and is
#     missed. Widening the grep to the path's directory prefixes was measured
#     and rejected: `docs/product/` is spelled in a dozen modules' prose, so
#     every delta would refuse and the mechanism would never fire once.
#   * It does not distinguish a module that READS a docs file from one that
#     merely NAMES it in a docstring. It refuses on either, which is the safe
#     direction and is why a delta touching `docs/product/architecture.md`
#     never reuses on this tree.

#: What a docs-only reuse rests on. Set by `loop_docs_only_reuse` on the way to
#: exit 0 and read by the REUSED line, the `loop:` cell and the row that is
#: banked afterwards. Empty until it has run, and empty is honest rather than
#: stale — the same contract `LOOP_ENV_COMPONENTS` keeps above.
LOOP_REUSE_TREE=""
LOOP_REUSE_N=""

#: The sentence a REFUSED reuse prints, or empty when the delta was simply not
#: docs-only. The distinction is the point: "this is an ordinary mixed delta" is
#: not news and must not add a line to every miss banner in the tree, while
#: "this WAS docs-only and the reuse was refused anyway" is the one thing a
#: reader needs to see, because it is the case where a green would have been
#: cheap and was declined on purpose.
LOOP_REUSE_WHY=""

#: The prefix, cited rather than re-listed — `loop_attribute_head_detail`'s own
#: `docs/` and for its reasons. One constant so the counter and the reuse can
#: never disagree about what "docs" means.
LOOP_DOCS_PREFIX='docs/'

# loop_docs_only_reuse <the attributor's token> <the attributor's detail>
#   0  the banked pytest verdict may stand in; LOOP_REUSE_TREE and
#      LOOP_REUSE_N say what it rests on and how big the delta was.
#   1  measure. LOOP_REUSE_WHY carries a sentence when the refusal is worth
#      printing, and is EMPTY when this was never a docs-only delta at all.
loop_docs_only_reuse() {
    local token=$1 detail=$2 basis head files p n hit banked_tree committed
    LOOP_REUSE_TREE=""
    LOOP_REUSE_N=""
    LOOP_REUSE_WHY=""
    # `tree` ALONE. An `env:` token means an input the suite stands on moved,
    # and a `scope` token means the selection itself did; neither is a delta a
    # path prefix can vouch for.
    [ "$token" = "tree" ] || return 1
    basis=$(printf '%s\n' "$detail" | sed -n 's/^reuse-basis: //p') || return 1
    basis=${basis##*$'\n'}
    [ -n "$basis" ] || return 1
    head=$(loop_component_value "$basis" head)
    [ -n "$head" ] || return 1
    # ANCESTRY, ASKED OF GIT AND NEVER ASSUMED. A banked head that is not an
    # ancestor of HEAD is a row from another line of development, and
    # `git diff A B` between two such points is not "what happened since".
    git merge-base --is-ancestor "$head" HEAD >/dev/null 2>&1 || return 1
    files=$(git diff --name-only "$head" HEAD 2>/dev/null) || return 1
    # NO COMMIT SINCE THE BANKED HEAD means the tree moved in the WORKING tree,
    # which is a builder editing its own checkout — deliberately not the shape
    # this reuse covers, and the same rule `loop_attribute_head_detail` states.
    [ -n "$files" ] || return 1
    n=0
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        case "$p" in
        "$LOOP_DOCS_PREFIX"*) ;;
        *) return 1 ;;
        esac
        n=$((n + 1))
    done <<EOF
$files
EOF
    [ "$n" -gt 0 ] || return 1
    # A DIRTY WORKING TREE IS NEVER DOCS-ONLY. The delta above is the COMMITTED
    # one; an uncommitted edit is a byte nobody can name, it moves the measured
    # tree (`gate_measured_tree` reads through `git add -A`), and it is exactly
    # how a builder's half-finished `apps/` change would ride in under a docs
    # commit's cover. `*.log` files are ignored and so are invisible here,
    # which is why the gate's own transcript does not refuse its own reuse.
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        LOOP_REUSE_WHY="docs-only delta, but the WORKING TREE is not clean: an uncommitted edit is not a delta anyone can name — measuring"
        return 1
    fi
    # AND NEITHER WAS THE BANKED RUN'S, WHICH IS THE OTHER HALF OF THE SAME
    # SENTENCE AND WAS MISSING FOR A WHOLE CYCLE (R3's F1). The clause above
    # holds THIS run's working tree to the committed delta it is claiming; every
    # word of that argument applies to the run the verdict is being INHERITED
    # from, and nothing above asked. A `--loop` verdict is keyed on the MEASURED
    # WORKING TREE — `gate_measured_tree` reads through `git add -A` — and a
    # builder's working tree is dirty most of the time it is being gated, so a
    # perfectly ordinary bank can carry `head=C` beside a tree that is NOT C's.
    # Inherit it under a docs commit and the green is about bytes nobody
    # committed: commit a red test, leave the uncommitted edit that greens it,
    # bank, restore the red bytes, commit a docs row — and the reuse hands out a
    # green over a red committed suite, then banks a reusable reuse row saying so.
    #
    # THE QUESTION IS ASKED OF GIT AND THE ANSWER IS AN EQUALITY, not a
    # heuristic: the basis row's `tree=` either IS THE MEASURED TREE OF `<head>`
    # or the row is not a verdict about any committed tree and cannot vouch for
    # one. A row too old to carry a `tree=` component, or a head this checkout
    # cannot resolve, is the same answer for the same reason — a basis that
    # cannot be checked is a basis that has not been.
    #
    # AND BOTH SIDES OF IT ARE THE SAME ARITHMETIC, which they were not. A
    # `--loop` row's `tree=` is written from `gate_measured_tree` — the working
    # tree with every DECLARED derived path subtracted — and this compared it
    # against a RAW `<head>^{tree}`. Identical wherever nothing is declared, so
    # the disagreement was invisible on this template; on a product that
    # declares one they can never be equal, and the docs-only reuse was closed
    # to exactly the products the road was widened for. `gate_measured_tree_of`
    # is the same subtraction asked of a ref, and the guard this equality
    # exists to be — a bank taken on a DIRTY working tree is no basis — is
    # untouched: measured-working equals measured-committed if and only if the
    # tree was clean when the bank was taken.
    #
    # AND THE LOCAL IS NOT CALLED `head_tree`, WHICH COST A GATE LEG TO LEARN.
    # `scripts/tests/test_pipefail_readers.sh`'s census matches `\| *head` over
    # the shipped lines, so `|| head_tree=""` reads as a pipe into `head` and
    # the line reds as an early-exit reader that is not there. Renaming is the
    # fix; a valve would be spending a declared escape on a coincidence.
    banked_tree=$(loop_component_value "$basis" tree)
    committed=$(gate_measured_tree_of "$head" 2>/dev/null) || committed=""
    if [ -z "$banked_tree" ] || [ -z "$committed" ] || [ "$banked_tree" != "$committed" ]; then
        LOOP_REUSE_WHY="the banked verdict was measured on a tree that is not its head's measured tree — measuring"
        return 1
    fi
    # THE POPULATION IS DERIVED, PER CHANGED PATH, AT RUN TIME. A hand list of
    # "the docs a test reads" is right on the day it is written; this asks the
    # tree. `-F` because a path is a literal, and `-l` because the first module
    # naming it is the whole answer.
    #
    # AND THE SENTENCE SAYS WHAT THIS DOES, NOT WHAT IT WISHES IT DID. The
    # question asked is "is this path SPELLED in any module under `apps/`",
    # which is fail-closed and wider than "a collected test reads it": the first
    # hit wins and it need not be a test (`apps/core/integrations.py` is a real
    # one), and a mention in a docstring refuses just as a real read does. The
    # refusal used to claim the narrower thing, which is a message naming a
    # cause it has not proven.
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        # READ WHOLE, THEN SLICE — never `| head -1`. The reader would close the
        # pipe under `grep -rl`, and a producer with more than the pipe buffer
        # still to write takes SIGPIPE and dies 141, which `pipefail` hands to
        # the caller as a failure of a search that actually MATCHED.
        hit=$(grep -rlF "$p" apps/ --include='*.py' 2>/dev/null) || hit=""
        hit=${hit%%$'\n'*}
        if [ -n "$hit" ]; then
            LOOP_REUSE_WHY="docs-only delta touches a path spelled in a module under apps/: ${p} (named in ${hit}) — measuring"
            return 1
        fi
    done <<EOF
$files
EOF
    # ONE READ OF THE ROW, not two. The basis check above already resolved this
    # and refused an empty one; re-reading it here would be a second opinion
    # about the same field, and the day the two disagree is the day the reuse
    # rests on a tree the refusal never looked at.
    LOOP_REUSE_TREE="$banked_tree"
    LOOP_REUSE_N="$n"
    return 0
}

# loop_ledger_lookup <key> → the most recent matching line on stdout, exit 0;
# exit 1 on ANY doubt at all. There is deliberately no exit 2 on this path: a
# cache that can break a gate is worse than no cache.
loop_ledger_lookup() {
    local key=$1 path line
    printf '%s' "$key" | grep -E "$LOOP_KEY_RE" >/dev/null || return 1
    path=$(loop_ledger_path) || return 1
    [ -f "$path" ] || return 1
    line=$(grep -F " $key loop " "$path" | grep "^$LOOP_LEDGER_SCHEMA " | tail -1)
    [ -n "$line" ] || return 1
    printf '%s\n' "$line"
}

# ---- the run log ------------------------------------------------------------

GATE_RUN_TREE=""    # what the run started on
GATE_RUN_LEG=""     # the leg now running, as gate_leg last named it
GATE_RUN_T0=""      # epoch seconds at start
GATE_RUN_SETTLED="" # set once this run's one line (or its verdict) is written
GATE_RUN_ARMED=""   # set by gate_run_start; every helper no-ops without it
GATE_RUN_CALLER="unstated" # resolved ONCE at start, so the note is printed
#                          # once and a trap firing after a kill cannot re-derive
#                          # a different answer than the line the run announced.

# Only the FULL gate calls this. `--fast` writes nothing anywhere; `--loop`
# writes NOTHING IN THIS SECTION and one row of its own in the LOOP ledger
# above. The blanket claim that used to stand on this line was superseded in the
# commit that made it false — see the loop-ledger section's own note on why the
# retired sentence is described there rather than re-spelled.
gate_run_start() {
    GATE_RUN_TREE=${1:-unknown-tree}
    GATE_RUN_T0=$(date +%s)
    GATE_RUN_CALLER=$(gate_caller)
    GATE_RUN_ARMED=1
}

gate_leg() {
    GATE_RUN_LEG=$1
    echo "- $2"
}

# One line, appended, once — idempotent by the settled flag, so a killed run
# whose EXIT trap then fires cannot relabel itself red.
gate_run_note() {
    [ -n "$GATE_RUN_ARMED" ] || return 0
    [ -z "$GATE_RUN_SETTLED" ] || return 0
    GATE_RUN_SETTLED=1
    local path
    path=$(gate_runs_path) || path="<no git directory>"
    if ! printf '%s %s %s %s caller=%s\n' "$GATE_LEDGER_SCHEMA" "$GATE_RUN_TREE" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$GATE_RUN_CALLER" >>"$path"; then
        printf 'run log could not be written to %s: %s is unrecorded\n' "$path" "$1" >&2 || true
    fi
}

gate_run_verdict_written() {
    [ -n "$GATE_RUN_ARMED" ] || return 0
    GATE_RUN_SETTLED=1
}

# The duration of a COMPLETED full run, for the next run's announcement.
gate_run_last_full() {
    [ -n "$GATE_RUN_ARMED" ] || return 0
    [ -n "$GATE_RUN_T0" ] || return 0
    local path
    path=$(gate_last_full_path) || return 0
    printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$(($(date +%s) - GATE_RUN_T0))" "$1" >>"$path" || true
}

# From the full gate's EXIT trap: decide the outcome when the gate has not
# already said. 129/130/143 without a settlement is a KILL that hit a leg's
# child — it must never be relabelled red.
gate_run_finish() {
    [ -n "$GATE_RUN_ARMED" ] || return 0
    local rc=${1:-0}
    case "$rc" in
    0) gate_run_note "unsettled" ;;
    2) gate_run_note "exit-2:${GATE_RUN_LEG:-before-first-leg}" ;;
    129 | 130 | 143) gate_run_note "killed:${GATE_RUN_LEG:-before-first-leg}" ;;
    *) gate_run_note "red:${GATE_RUN_LEG:-before-first-leg}" ;;
    esac
    case "$rc" in
    0) gate_run_last_full green ;;
    2) gate_run_last_full exit-2 ;;
    129 | 130 | 143) : ;; # a killed run's length is the killer's choice
    *) gate_run_last_full red ;;
    esac
}

# From the full gate's TERM/INT/HUP trap: name the leg, write the line, exit
# 143 so the EXIT trap still runs. PIPE ignored first — after a kill the reader
# is usually already gone.
gate_run_killed() {
    trap '' PIPE
    gate_run_note "killed:${GATE_RUN_LEG:-before-first-leg}"
    exit 143
}

# gate_run_lookup <tree> → the OUTCOME word of the most recent run-log line for
# that tree, so a reader can tell a red run from a killed one.
gate_run_lookup() {
    local tree=$1 path line
    path=$(gate_runs_path) || return 1
    [ -f "$path" ] || return 1
    line=$(grep -F " $tree " "$path" | grep "^$GATE_LEDGER_SCHEMA " | tail -1)
    [ -n "$line" ] || return 1
    awk '{print $4}' <<<"$line"
}

# Printed by the full gate before its first leg: what happened to the previous
# run on THIS tree, and a measured time estimate.
gate_run_announce() {
    local path secs line prior
    # The caller this run will record, said out loud before the first leg.
    # A field nobody can see at the time it is written is a field nobody
    # notices going wrong.
    if [ "$GATE_RUN_CALLER" = "unstated" ]; then
        echo "- caller: unstated (set DJB_GATE_CALLER to one of: $GATE_CALLER_KINDS)"
    else
        echo "- caller: $GATE_RUN_CALLER (DJB_GATE_CALLER)"
    fi
    # And what made this run legal at all, said before the first leg for the
    # same reason: a field nobody can see at the time it is written is a field
    # nobody notices going wrong.
    if [ -n "${GATE_RUN_SANCTION:-}" ]; then
        echo "- sanction: $GATE_RUN_SANCTION"
    fi
    if [ -n "$GATE_RUN_TREE" ] && prior=$(gate_run_lookup "$GATE_RUN_TREE"); then
        case "$prior" in
        killed:*) echo "- the previous run on this tree was KILLED during ${prior#killed:} — no verdict, no red; nothing was judged" ;;
        tree-changed) echo "- the previous run on this tree passed but the tree changed mid-run — no verdict" ;;
        red:*) echo "- the previous run on this tree went red in ${prior#red:}" ;;
        exit-2:*) echo "- the previous run on this tree found ENFORCEMENT BROKEN in ${prior#exit-2:}" ;;
        unsettled) echo "- the previous run on this tree passed and never settled its record — a gate wiring bug, not your change" ;;
        *) echo "- the previous run on this tree ended: $prior" ;;
        esac
    fi
    path=$(gate_last_full_path) || return 0
    line=""
    [ -f "$path" ] && line=$(grep ' green$' "$path" | tail -1 || true)
    if [ -n "$line" ]; then
        secs=$(awk '{print $2}' <<<"$line")
        echo "- full gate — the last green run here took $((secs / 60))m$((secs % 60))s"
    fi
}
