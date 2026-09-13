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

gate_ledger_path() { gate_local_path djb-gate-verdicts; }
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
GATE_TREE_DECL_SOURCES='scripts/*.sh quality/*.py frontend/scripts/*.sh'

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

# The content address of the working state. GIT_INDEX_FILE points `git add` at
# a scratch index, so the real index is untouched; `git add -A` honours
# .gitignore, which makes the key "the content the gate can read" rather than
# "the content plus every build artefact" — minus the paths a leg DECLARES it
# derives, which makes it "the content the gate can read AND something it
# measures reads back".
gate_measured_tree() {
    local idx tree root paths p
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

# gate_ledger_record <tree> <legs-csv> — one line, appended, schema first.
gate_ledger_record() {
    local tree=$1 legs=$2 path sanction
    path=$(gate_ledger_path) || return 1
    # Newlines would make one row into two, and a row nothing can parse is worse
    # than a row that says nothing. check.sh's shape check already refuses them
    # at the door; this is the ledger refusing to be the place it matters.
    sanction=$(printf '%s' "${GATE_RUN_SANCTION:-}" | tr '\n' ' ')
    if [ -n "$sanction" ]; then
        printf '%s %s full %s %s caller=%s sanction=%s%s\n' \
            "$GATE_LEDGER_SCHEMA" "$tree" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$legs" \
            "$(gate_caller)" "$sanction" "$(gate_ledger_cost_fields)" >>"$path"
    else
        printf '%s %s full %s %s caller=%s%s\n' \
            "$GATE_LEDGER_SCHEMA" "$tree" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$legs" \
            "$(gate_caller)" "$(gate_ledger_cost_fields)" >>"$path"
    fi
}

# gate_ledger_lookup <tree> → most recent matching line on stdout, exit 0;
# exit 1 when the tree has no verdict.
gate_ledger_lookup() {
    local tree=$1 path line
    path=$(gate_ledger_path) || return 1
    [ -f "$path" ] || return 1
    line=$(grep -F " $tree full " "$path" | grep "^$GATE_LEDGER_SCHEMA " | tail -1)
    [ -n "$line" ] || return 1
    printf '%s\n' "$line"
}

# gate_has_green <tree> → exit 0 iff a full green run measured this tree.
gate_has_green() { gate_ledger_lookup "$1" >/dev/null; }

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
LOOP_ENV_COMPONENT_FIELDS='env-file excluded dists head merge-base'

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

# loop_env_fingerprint — one digest of everything the suite stands on that the
# tree hash does not carry, on stdout. Exit 0 derived · 1 could not look.
#
# FOUR INPUTS:
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
#   * HEAD, and the MERGE-BASE with `refs/heads/main` — see the header.
loop_env_fingerprint() {
    local env_file=.env keys excluded dists head base venv site env_digest
    keys=$(loop_env_derived_keys)
    if [ -f "$env_file" ]; then
        if [ -z "$keys" ]; then
            excluded="UNDECLARED(whole-file)"
            env_digest=$(shasum -a 256 <"$env_file" | awk '{print $1}')
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
            ' "$env_file" | shasum -a 256 | awk '{print $1}')
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
    dists=$(printf '%s' "$site" | shasum -a 256 | awk '{print $1}')

    head=$(git rev-parse -q --verify HEAD 2>/dev/null || printf 'unborn')
    base="no-local-main"
    if git rev-parse -q --verify refs/heads/main >/dev/null 2>&1; then
        base=$(git merge-base HEAD refs/heads/main 2>/dev/null || printf 'no-merge-base')
    fi

    # THE COMPONENTS, KEPT FOR PRINTING — and the hashed line below is NOT
    # rebuilt from them. The composition that feeds `shasum` is byte-identical
    # to what it has always been, because changing it would silently invalidate
    # every banked row in every checkout; the printable line is a second,
    # separately spelled string whose field names are the ones the miss banner
    # and the criteria use (`env-file=` for the .env digest, which the hashed
    # line calls `env=` and which is NOT the whole fingerprint).
    LOOP_ENV_COMPONENTS=$(printf 'env-file=%s excluded=%s dists=%s head=%s merge-base=%s' \
        "$env_digest" "$excluded" "$dists" "$head" "$base")
    LOOP_ENV_FINGERPRINT=$(printf 'env=%s excluded=%s dists=%s head=%s merge-base=%s\n' \
        "$env_digest" "$excluded" "$dists" "$head" "$base" |
        shasum -a 256 | awk '{print $1}')
    [ -n "$LOOP_ENV_FINGERPRINT" ] || return 1
    printf '%s\n' "$LOOP_ENV_FINGERPRINT"
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
        shasum -a 256 | awk '{print $1}')
    [ -n "$digest" ] || return 1
    printf '%s:%s\n' "$LOOP_LEDGER_SCHEMA" "$digest"
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
loop_ledger_record() {
    local key=$1 scope=$2 passes=${3:-1} tree=${4:-} env=${5:-} path
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
    local components="${LOOP_ENV_COMPONENTS:-}"
    printf '%s %s loop %s caller=%s scope=%s passes=%s tree=%s env=%s%s%s\n' \
        "$LOOP_LEDGER_SCHEMA" "$key" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(gate_caller)" \
        "$(printf '%s' "$scope" | tr '\n ' '__')" "$passes" \
        "${tree:-unstated}" "${env:-unstated}" \
        "${components:+ $components}" "$(gate_ledger_cost_fields)" >>"$path"
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
# ledger commit is a re-measure bought by a file no test reads, and until this
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
