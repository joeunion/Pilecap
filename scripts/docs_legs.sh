#!/usr/bin/env bash
# The four `--fast` census bodies that ask a closed question of a DOCUMENT
# rather than of the code: the two extracted from `scripts/publish.sh` so its
# release-time scan and `scripts/check.sh`'s per-rung legs share ONE
# implementation, and the two new ones that had no home at all.
#
#   docs_adr_census <root> <file-list-file>      · publish.sh + check.sh --fast
#   docs_dangling_docs <root> <file-list-file> [<trimmed> <measured>]   · publish.sh + check.sh --fast (both classes)
#   docs_adr_census_loop / docs_dangling_docs_loop  · check.sh's per-rung bodies
#   docs_derived_check <root>                    · docs_dangling_docs_loop, the whole tree
#   docs_current_state_check <root> <list>       · docs_dangling_docs_loop, the changed SHIP pages
#   docs_ci_env_leg                              · check.sh --fast
#
# Sourced by scripts/publish.sh, scripts/check.sh and
# quality/tests/test_docs_legs.py's worlds. The two `_loop` bodies also need
# `bucket_for_path` from scripts/archaeology_lib.sh, which every one of those
# three sources FIRST; they refuse (exit 2) rather than scan unfiltered if it is
# absent.
# BASH ONLY, for the reason gate_ledger.sh states: sourced into an interactive
# zsh, `local path` ties to $PATH and every helper dies silently.
#
# NOT EXECUTABLE, AND THAT IS THE DECLARATION, not an oversight — the same one
# `scripts/archaeology_lib.sh` makes in its own header: this file reports no
# verdict of its own, it hands a scan result to whoever sourced it, and the
# caller owns the exit status. A library beside secrets_scan.sh and db.sh, not
# an instrument beside them — which is also why it owes no row in the
# instrument census, whose population is the tree's EXECUTABLE files plus a
# pinned list, and for which a row naming a file the derivation does not name
# is a GHOST at exit 2. Measured, not assumed; the rung's report carries it.
#
# ---------------------------------------------------------------------------
# WHY THE FIRST TWO WERE EXTRACTED. They lived in `scripts/publish.sh` and ran
# ONCE, at release, over the exported artifact. That is the belt and it stays;
# what it cannot be is the thing a builder meets. Five v2.0.0 scrub violations
# sat on main for days because the only reader of those two questions ran at
# publication time. The `archaeology` leg had exactly this shape and exactly
# this fix a cycle earlier (scripts/archaeology_lib.sh's header): one body, two
# callers — the whole artifact at release, the active rung's changed files at
# every commit — so a maintainer meets a dead citation AT THE COMMIT THAT
# WRITES IT, where the fix is the line still in their head.
#
# WHY THE OTHER TWO ARE HERE AND NOT INLINE IN `check.sh`. A drive cannot run a
# nested `./scripts/check.sh` — the per-checkout gate lock refuses it, so a
# case that shelled out to the gate would go red for the lock and not for the
# property. A leg body a drive can source is a leg body a drive can drive; one
# inlined in `check.sh` is provable only by reading `check.sh` as text. The
# file's NAME is `docs_legs.sh` because the brief that created it named the two
# docs bodies; `loop-names` and `ci-env` are census bodies of the same tier and
# the same shape, and are stated here rather than given a second library.
# ---------------------------------------------------------------------------

# THE REFUSAL SEAM — scripts/gate_refuse.sh, sourced by this library's own
# directory and guarded against a second source, exactly as archaeology_lib.sh
# does it. Every could-not-look headline below goes through `gate_refuse` so
# the leg banner in `check.sh` can name which census could not read what.
# shellcheck source=scripts/gate_refuse.sh
if [ -z "${GATE_REFUSE_SOURCED:-}" ]; then
    case "${BASH_SOURCE[0]:-}" in
    */*) . "${BASH_SOURCE[0]%/*}/gate_refuse.sh" ;;
    *) . scripts/gate_refuse.sh ;;
    esac
fi

# THE SCOPE NOUN, set by the caller around its own call. `publish.sh` asks the
# question of an exported ARTIFACT; `check.sh` asks it of the TREE. The finding
# lines are otherwise identical, and the wording of publish.sh's is a published
# contract (`quality/tests/test_publish.py` reads it), so it is the default and
# a caller that means something else says so.
DOCS_LEGS_SCOPE_NOUN=${DOCS_LEGS_SCOPE_NOUN:-the artifact}

# THE ADR DIRECTORY: one file per id, `<id>.md`, headed `# ADR <id>`. This file
# SHIPS (bucket R3), so the directory is named without the markdown suffix and is no pointer site.
DOCS_ADR_DIR=${DOCS_ADR_DIR:-docs/product/adrs}

# The two greps, in one place. Neither matches its own text (after the id keyword and after
# `docs/` comes `[`), which is why they can be spelled here at all.
DOCS_ADR_RE='ADR [a-z][a-z0-9_]*(-[a-z][a-z0-9_]*)*-[0-9]+[a-z]?'
DOCS_REF_RE='docs/[A-Za-z0-9._/-]+\.md'

# Set by the two scans; the caller prints them. `publish.sh`'s two count lines
# are byte-for-byte the ones it always printed, computed here instead of there.
DOCS_ADR_SITES=0
DOCS_ADR_IDS=0
DOCS_DANGLING_SITES=0
DOCS_DANGLING_PATH_SITES=0

# The checkout this library sits in: the `dangling-paths` reader and its interpreter are its own, never the scanned root's.
case "${BASH_SOURCE[0]:-}" in
*/*) DOCS_LEGS_HOME=$(cd "${BASH_SOURCE[0]%/*}/.." && pwd) ;;
*) DOCS_LEGS_HOME=$(cd .. && pwd) ;;
esac

# docs_legs_read_list <root> <file-list-file> — fills the global array
# DOCS_LEGS_FILES with the paths in a NUL-separated list that name an EXISTING
# regular file UNDER <root>, keeping them relative as given (the scans `cd` to
# <root>, so relative is the only form that works for both callers). A deleted
# path in a changed-file set is a path with nothing to read, not a file that
# scans clean.
DOCS_LEGS_FILES=()
docs_legs_read_list() {
    local root=$1 list=$2 f
    DOCS_LEGS_FILES=()
    [ -r "$list" ] || return 2
    while IFS= read -r -d '' f; do
        [ -n "$f" ] || continue
        [ -f "$root/$f" ] || continue
        DOCS_LEGS_FILES+=("$f")
    done <"$list"
    return 0
}

# docs_adr_census <root> <file-list-file>
#
# Every `ADR <id>` cited by any file in the list must resolve to `$DOCS_ADR_DIR/<id>.md` under
# <root>, and every file there must be headed `# ADR <its own name>`. Prints one
# `adr-census: <id> resolves nowhere in <noun> — cited in <file>` per dead citation and one
# `adr-census: <file> is headed "<line>", not "# ADR <id>" — the filename is the id` per
# mismatched file, TO STDOUT AND NOTHING ELSE; the caller counts those lines and owns the verdict.
#
# Sets DOCS_ADR_SITES and DOCS_ADR_IDS. Returns 0 once every file has been read, 2 if it could
# not look — no directory, a directory holding no ADR file, or a `grep` that could not read the
# set. Never 1: a finding is a line, not a status, here.
docs_adr_census() {
    local root=$1 list=$2 f stem head homes cited rc line id file
    DOCS_ADR_SITES=0
    DOCS_ADR_IDS=0

    if [ ! -d "$root/$DOCS_ADR_DIR" ]; then
        gate_refuse "adr-census: $DOCS_ADR_DIR is not in ${DOCS_LEGS_SCOPE_NOUN} — the decision log does"
        echo "   not ship, so no citation can resolve. That is the ruling broken, not a violation." >&2
        return 2
    fi
    homes=$(mktemp "${TMPDIR:-/tmp}/djb-docs-homes.XXXXXX") || return 2
    for f in "$root/$DOCS_ADR_DIR"/*.md; do
        [ -f "$f" ] || continue
        stem=${f##*/}
        stem=${stem%.md}
        [ "$stem" != "README" ] || continue
        IFS= read -r head <"$f" || head=""
        if [ "$head" != "# ADR $stem" ]; then
            printf 'adr-census: %s is headed "%s", not "# ADR %s" — the filename is the id\n' \
                "$DOCS_ADR_DIR/$stem.md" "$head" "$stem"
        fi
        printf '%s\n' "$stem" >>"$homes"
    done
    if [ ! -s "$homes" ]; then
        gate_refuse "adr-census: $DOCS_ADR_DIR holds no ADR file — the grammar this leg reads is one"
        echo "   file per id, <id>.md, and a directory with none is this leg looking at the wrong thing." >&2
        rm -f "$homes"
        return 2
    fi
    LC_ALL=C sort -u -o "$homes" "$homes"
    DOCS_ADR_IDS=$(wc -l <"$homes" | tr -d ' ')

    if ! docs_legs_read_list "$root" "$list"; then
        gate_refuse "adr-census: the file list could not be read — nothing was scanned"
        rm -f "$homes"
        return 2
    fi
    cited=$(mktemp "${TMPDIR:-/tmp}/djb-docs-cited.XXXXXX") || {
        rm -f "$homes"
        return 2
    }
    if [ "${#DOCS_LEGS_FILES[@]}" -gt 0 ]; then
        # `-H` ALWAYS, archaeology_scan_files' lesson paid in full: grep only
        # PREFIXES the filename when handed more than one, so a rung that
        # changed exactly one file would otherwise hand the parser a bare
        # match with no filename at all, which the parser reads as a citation
        # in a file named after the match — printed with total confidence.
        set +e
        (cd "$root" && grep -HIoE "$DOCS_ADR_RE" -- "${DOCS_LEGS_FILES[@]}") >"${cited}.raw" 2>/dev/null
        rc=$?
        set -e
        if [ "$rc" -gt 1 ]; then
            gate_refuse "adr-census: the citation scan could not read ${DOCS_LEGS_SCOPE_NOUN}"
            echo "   (grep exited $rc). A tree nobody looked at is not a clean tree." >&2
            rm -f "$homes" "$cited" "${cited}.raw"
            return 2
        fi
        sed 's|^\./||' "${cited}.raw" | LC_ALL=C sort -u >"$cited"
        rm -f "${cited}.raw"
    else
        : >"$cited"
    fi

    DOCS_ADR_SITES=$(LC_ALL=C sort -u -t: -k2 "$cited" | wc -l | tr -d ' ')
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        id=${line#*:}
        id=${id#ADR }
        file=${line%%:*}
        if ! grep -qxF "$id" "$homes"; then
            printf 'adr-census: ADR %s resolves nowhere in %s — cited in %s\n' \
                "$id" "$DOCS_LEGS_SCOPE_NOUN" "$file"
        fi
    done <"$cited"
    rm -f "$homes" "$cited"
    return 0
}

# docs_dangling_docs <root> <file-list-file> [<trimmed> <measured>] — `quality.djb.legs.dangling_docs` (both classes); findings on stdout, 2 when it could not look.
# Sets DOCS_DANGLING_SITES and DOCS_DANGLING_PATH_SITES from the module's sites file.
docs_dangling_docs() {
    local root=$1 list=$2 py sites rc=0
    local -a excuse=()
    [ -z "${3:-}" ] || excuse+=(--trimmed "$3")
    [ -z "${4:-}" ] || excuse+=(--measured "$4")
    DOCS_DANGLING_SITES=0
    DOCS_DANGLING_PATH_SITES=0
    py=$(checkout_python "$DOCS_LEGS_HOME") || {
        gate_refuse "dangling-docs: no interpreter at $DOCS_LEGS_HOME/.venv — nothing was scanned"
        return 2
    }
    sites=$(mktemp "${TMPDIR:-/tmp}/djb-docs-sites.XXXXXX") || return 2
    "$py" -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from quality.djb.legs.dangling_docs import main; sys.exit(main())' \
        "$DOCS_LEGS_HOME" "$root" "$list" --noun "$DOCS_LEGS_SCOPE_NOUN" --sites-file "$sites" ${excuse[@]+"${excuse[@]}"} || rc=$?
    if [ "$rc" != "0" ]; then
        rm -f "$sites"
        return 2
    fi
    read -r DOCS_DANGLING_SITES DOCS_DANGLING_PATH_SITES <"$sites" || true
    rm -f "$sites"
    return 0
}

# --------------------------------------------------------------------------
# THE PER-RUNG BODIES. Each is `archaeology_loop`'s shape exactly: derive the
# active rung's changed files with `secrets_scan_changed_files` (ONE derivation
# in this tree, never a second copy of it), print the basis it derived them
# from, scan, and return 0 clean · 1 a finding · 2 could-not-look.
#
# THE BUCKET FILTER, AND WHY IT IS THE SAME ONE. These two legs shipped without
# it, on the argument that a ledger row pointing at a file that does not exist
# is as dead for its reader as a docstring pointing at one. MEASURED, the first
# time the leg met an ordinary ledger commit: four violations at once, every one
# of them a FORWARD id — a decision the ledger is proposing and nobody has
# written yet. That is the same class the archaeology leg's own comment names in
# this tree: a SKELETON ledger row citing an id it does not yet resolve is
# expected vocabulary, not a dead citation, and a census that reddens on it
# reddens on every PM ledger commit there will ever be.
#
# So the population is the changed files whose bucket is SHIP, classified by
# `bucket_for_path` (scripts/archaeology_lib.sh) — the SAME call
# `archaeology_loop` makes, never a second copy of the question "is this file
# SHIP". The caller must have sourced that library; if it has not, these legs
# say so and refuse rather than quietly scanning everything.
#
# THE SET-ASIDE COUNT IS PRINTED, always. A narrowing nobody can see is a reader
# taking "no findings" for "every changed file was read", which is the same
# defect one layer down from the thin basis below.
#
# WHAT THIS GIVES UP, declared: a dangling pointer or an unresolvable id written
# into a SKELETON or TRIM file reaches main unseen here. It is not lost — those
# files ship TRIMMED (a SKELETON is a header plus one marked worked example; a
# TRIM file does not ship at all), so the release-time belt in `publish.sh`,
# which reads the exported ARTIFACT, was never going to see the row either. The
# gap is between a ledger row and its own reader, and it is the price of a hook
# the PM can commit through.
#
# THE THIN BASIS IS A NARROWER LOOK, NEVER A REFUSAL — inherited whole from
# `secrets_scan_changed_files`, which answers "the uncommitted set" in a
# checkout with no local main and SAYS SO. These legs print that sentence like
# the archaeology leg does, because a narrowed scan that does not say what it
# narrowed to is a reader taking "no findings" for "the tree is clean".
# --------------------------------------------------------------------------

DOCS_LEGS_LIST=""
DOCS_LEGS_SHIP_N=0
DOCS_LEGS_ASIDE_N=0

# _docs_legs_changed — derive the active rung's changed files, narrow them to
# bucket SHIP, print the basis and the two counts. Leaves the filtered
# NUL-separated set in DOCS_LEGS_LIST for the caller to hand to a scan, and the
# caller removes it. 0 ready · 2 could-not-look.
_docs_legs_changed() {
    local raw f bucket
    if ! command -v bucket_for_path >/dev/null 2>&1; then
        gate_refuse "docs censuses: bucket_for_path is not defined — the caller has not sourced"
        echo "   scripts/archaeology_lib.sh, so the SHIP/SKELETON/TRIM classifier these legs" >&2
        echo "   narrow with is absent. Scanning everything instead would redden this gate on" >&2
        echo "   every ledger commit; scanning nothing would be a green over nothing. Neither" >&2
        echo "   is a verdict." >&2
        return 2
    fi
    DOCS_LEGS_SHIP_N=0
    DOCS_LEGS_ASIDE_N=0
    raw=$(mktemp "${TMPDIR:-/tmp}/djb-docs-raw.XXXXXX") || return 2
    if ! secrets_scan_changed_files "$raw"; then
        rm -f "$raw"
        return 2
    fi
    echo "  basis: ${SECRETS_SCAN_BASIS}"

    DOCS_LEGS_LIST=$(mktemp "${TMPDIR:-/tmp}/djb-docs-changed.XXXXXX") || {
        rm -f "$raw"
        DOCS_LEGS_LIST=""
        return 2
    }
    : >"$DOCS_LEGS_LIST"
    while IFS= read -r -d '' f; do
        [ -n "$f" ] || continue
        [ -f "$f" ] || continue
        bucket=$(bucket_for_path "$f")
        if [ "$bucket" = "SHIP" ]; then
            printf '%s\0' "$f" >>"$DOCS_LEGS_LIST"
            DOCS_LEGS_SHIP_N=$((DOCS_LEGS_SHIP_N + 1))
        else
            DOCS_LEGS_ASIDE_N=$((DOCS_LEGS_ASIDE_N + 1))
        fi
    done <"$raw"
    rm -f "$raw"

    echo "  $DOCS_LEGS_SHIP_N ship file(s) scanned · $DOCS_LEGS_ASIDE_N skeleton/trim file(s) set aside"
    if [ "$DOCS_LEGS_ASIDE_N" -gt 0 ]; then
        echo "  (a ledger the platform ships as a skeleton carries FORWARD citations by design —"
        echo "  an id or a path it is proposing and nobody has written yet — and the row is"
        echo "  trimmed before it ever reaches an artifact, so neither half of this census was"
        echo "  ever its reader; bucket_for_path, scripts/archaeology_lib.sh)"
    fi
    return 0
}

# docs_adr_trigger_paragraphs <file> — `<id><TAB>rejected<TAB>trigger` (1/0) per
# ADR paragraph: from a line carrying `**ADR <id>` to the next blank line, the
# next such line, or a table row's end.
docs_adr_trigger_paragraphs() {
    awk '
        function flush() { if (id != "") printf "%s\t%d\t%d\n", id, rej, trig; id = ""; rej = 0; trig = 0 }
        {
            if ($0 ~ /^[ \t]*$/) { flush(); next }
            if (match($0, /\*\*ADR [a-z0-9]+-[a-z0-9]+/)) {
                flush(); id = substr($0, RSTART + 6, RLENGTH - 6)
            }
            if (id == "") next
            l = tolower($0)
            if (l ~ /rejected:/) rej = 1
            if (l ~ /trigger to revisit:/) trig = 1
            if ($0 ~ /^\|/) flush()
        }
        END { flush() }' "$1"
}

# docs_adr_triggers <root> <file-list-file> <base-commit|""> — one
# `adr-census: ADR <id> carries rejected: and no trigger to revisit: — <file>` line per ADR
# paragraph in a CHANGED file of the ADR directory that records a rejection without its trigger,
# unless that paragraph stood without one at <base> in the directory or in a `docs/product/*.md`
# (decision content predating the field is the owner's, wherever it was written; a paragraph born
# or touched now is born to standard). Base empty: HEAD is the reference.
docs_adr_triggers() {
    local root=$1 list=$2 rev=${3:-HEAD} h id rej trig was
    docs_legs_read_list "$root" "$list" || return 2
    was=$(
        cd "$root" || exit 0
        git ls-tree --name-only "$rev" docs/product/ "$DOCS_ADR_DIR/" 2>/dev/null | grep '\.md$' |
            while IFS= read -r h; do
                git show "$rev:$h" 2>/dev/null
                echo
            done | docs_adr_trigger_paragraphs /dev/stdin 2>/dev/null
    ) || was=""
    for h in "${DOCS_LEGS_FILES[@]}"; do
        case "$h" in "$DOCS_ADR_DIR"/*.md) ;; *) continue ;; esac
        while IFS="$(printf '\t')" read -r id rej trig; do
            [ -n "$id" ] && [ "$rej" = 1 ] && [ "$trig" = 0 ] || continue
            case "
${was}
" in
            *"
${id}	1	0
"*) continue ;;
            esac
            printf 'adr-census: ADR %s carries rejected: and no trigger to revisit: — %s\n' "$id" "$h"
        done <<EOF
$(docs_adr_trigger_paragraphs "$root/$h")
EOF
    done
    return 0
}

docs_adr_census_loop() {
    local rc bad out line
    DOCS_LEGS_SCOPE_NOUN="the tree"
    _docs_legs_changed || return 2
    if [ "$DOCS_LEGS_SHIP_N" = "0" ]; then
        rm -f "$DOCS_LEGS_LIST"
        echo "  NOTHING TO SCAN: the active rung changed no bucket-SHIP file."
        return 0
    fi

    out=$(mktemp "${TMPDIR:-/tmp}/djb-docs-adr-out.XXXXXX") || {
        rm -f "$DOCS_LEGS_LIST"
        return 2
    }
    set +e
    docs_adr_census "$PWD" "$DOCS_LEGS_LIST" >"$out"
    rc=$?
    [ "$rc" = "2" ] || docs_adr_triggers "$PWD" "$DOCS_LEGS_LIST" "${SECRETS_SCAN_BASE:-}" >>"$out" || rc=2
    set -e
    rm -f "$DOCS_LEGS_LIST"
    if [ "$rc" = "2" ]; then
        rm -f "$out"
        return 2
    fi

    echo "  $DOCS_ADR_SITES citation site(s) in the changed set · $DOCS_ADR_IDS ids resolvable in the ADR directory"
    bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "  VIOLATION  $line"
        bad=$((bad + 1))
    done <"$out"
    rm -f "$out"
    if [ "$bad" = "0" ]; then
        echo "  ok — every ADR id the active rung cites resolves to its file in the ADR directory"
        echo "  (publish.sh's whole-artifact scan stays the belt: a dead citation in a file"
        echo "  the active rung did not touch is invisible here by design)"
        return 0
    fi
    return 1
}

# _docs_legs_measured <out> — publish's R12 arm (`rules_for`), NUL-separated: the measured files
# every release trims, so a product tree never holds them. 2 when the arm yields none.
_docs_legs_measured() {
    local p hit n=0
    : >"$1"
    for p in $(declare -f rules_for | grep -B1 'hit="$hit R12"' | head -1 | tr '|)' '  '); do
        hit=$(rules_for "$p")
        [ "${hit// /}" = "R12" ] || continue
        printf '%s\0' "$p" >>"$1"
        n=$((n + 1))
    done
    if [ "$n" = "0" ]; then
        gate_refuse "dangling-docs: rules_for's R12 arm named no measured file — nothing was scanned"
        return 2
    fi
}

# docs_derived_check <root> — every derived block under <root> is its generator's output; 0 · 1 · 2.
# Whole tree, not the changed set: a block goes stale when its INPUT changes (an `apps.py`), not its page.
docs_derived_check() {
    local py
    py=$(checkout_python "$DOCS_LEGS_HOME") || {
        gate_refuse "derived-blocks: no interpreter at $DOCS_LEGS_HOME/.venv — nothing was checked"
        return 2
    }
    echo "  derived blocks (quality/docs_derived.py --check, the whole tree):"
    "$py" -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from quality.docs_derived import main; sys.exit(main())' \
        "$DOCS_LEGS_HOME" --root "$1" --check
}

# docs_current_state_check <root> <nul-list> — no listed SHIP page names a ledger id, a trimmed path
# or a future the tree passed (scripts/current_state_census.py); 0 · 1 · 2.
docs_current_state_check() {
    local py
    py=$(checkout_python "$DOCS_LEGS_HOME") || {
        gate_refuse "current-state: no interpreter at $DOCS_LEGS_HOME/.venv — nothing was checked"
        return 2
    }
    echo "  current state (scripts/current_state_census.py, the changed SHIP pages):"
    "$py" "$DOCS_LEGS_HOME/scripts/current_state_census.py" "$1" "$2" | while IFS= read -r line; do
        echo "  VIOLATION  $line"
    done
    return "${PIPESTATUS[0]}"
}

docs_dangling_docs_loop() {
    local rc bad out line measured derived=0
    DOCS_LEGS_SCOPE_NOUN="the tree"
    docs_derived_check "$PWD" || derived=$?
    [ "$derived" != "2" ] || return 2
    _docs_legs_changed || return 2
    if [ "$DOCS_LEGS_SHIP_N" = "0" ]; then
        rm -f "$DOCS_LEGS_LIST"
        echo "  NOTHING TO SCAN: the active rung changed no bucket-SHIP file."
        return "$derived"
    fi
    rc=0
    docs_current_state_check "$PWD" "$DOCS_LEGS_LIST" || rc=$?
    if [ "$rc" = "2" ]; then
        rm -f "$DOCS_LEGS_LIST"
        return 2
    fi
    [ "$rc" = "0" ] || derived=1

    measured=$(mktemp "${TMPDIR:-/tmp}/djb-docs-measured.XXXXXX") || {
        rm -f "$DOCS_LEGS_LIST"
        return 2
    }
    out=$(mktemp "${TMPDIR:-/tmp}/djb-docs-dang-out.XXXXXX") || {
        rm -f "$DOCS_LEGS_LIST" "$measured"
        return 2
    }
    if ! _docs_legs_measured "$measured"; then
        rm -f "$DOCS_LEGS_LIST" "$measured" "$out"
        return 2
    fi
    set +e
    docs_dangling_docs "$PWD" "$DOCS_LEGS_LIST" "" "$measured" >"$out"
    rc=$?
    set -e
    rm -f "$DOCS_LEGS_LIST" "$measured"
    if [ "$rc" = "2" ]; then
        rm -f "$out"
        return 2
    fi

    echo "  $DOCS_DANGLING_SITES pointer site(s) and $DOCS_DANGLING_PATH_SITES path site(s) in the changed set"
    bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "  VIOLATION  $line"
        bad=$((bad + 1))
    done <"$out"
    rm -f "$out"
    if [ "$bad" = "0" ]; then
        echo "  ok — every docs pointer and repository path the active rung spells exists in this tree"
        return "$derived"
    fi
    return 1
}

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# docs_ci_env_leg [readers] [workflows] [example] [test-settings] — the `ci-env`
# census: every name the settings read whose development value differs from the
# code's default is supplied by every workflow that runs the stack, or pinned by
# the test settings — and never both.
#
# Population: every `env.<type>("NAME"`, `os.environ.get`, `os.getenv` and
# `os.environ["NAME"]` under the readers (default `config/`, the test settings
# excluded), narrowed to the names `.env.example` gives a non-empty value that is
# not a spelling of the code's default; a default that is not a literal counts as
# different (the census cannot evaluate it).
# Workflows: every `*.yml`/`*.yaml` under the workflows directory (or the one
# file named) that runs `scripts/check.sh` or `scripts/ci_stack.sh` — each is
# censused on its own, since a key in one workflow supplies nothing to another.
# An empty value is a clearing (house rule 62), never a supply and never a
# second authority.
# The reader census is `quality/partition.py::environment_reads`'s grammar
# re-read here because that one is fixed to its own checkout's root.
# does-not-cover: VALUES — a wrong endpoint port is a green census and a red run.
# does-not-cover: a read whose name is computed (the `ANYMAIL_*` prefix scan).
# does-not-cover: a workflow that runs the suite by a script this selection does not name.
# Exit: 0 clean, or no workflow runs the stack (PRINTED) · 1 a name is missing
# from a workflow's env maps, or a supplied name is pinned by the test settings ·
# 2 could-not-look.
# --------------------------------------------------------------------------
DOCS_CI_ENV_READERS=${DOCS_CI_ENV_READERS:-config}
DOCS_CI_ENV_TEST_SETTINGS=${DOCS_CI_ENV_TEST_SETTINGS:-config/settings/test.py}
DOCS_CI_ENV_EXAMPLE=${DOCS_CI_ENV_EXAMPLE:-.env.example}
DOCS_CI_ENV_WORKFLOWS=${DOCS_CI_ENV_WORKFLOWS:-.github/workflows}


# docs_ci_env_keys <workflow-file> — prints every key under any `env:` map in
# the file, one per line. A real (small) indentation parse rather than a grep
# for a bare `NAME:` line: indentation is what makes a key a member of the
# `env:` map above it, and a census satisfied by a `with:` key would be
# satisfied by the wrong thing. Returns 2 when the file's indentation is not
# something this reader can follow (a tab, which YAML forbids), or when it
# holds no `env:` map at all — a workflow this reader cannot locate an `env:`
# map in is one it cannot answer about, which is could-not-look and not "every
# key is missing".
docs_ci_env_keys() {
    local wf=$1 rc
    set +e
    awk '/^\t/ { bad = 1 } END { exit bad ? 1 : 0 }' "$wf"
    rc=$?
    set -e
    if [ "$rc" != "0" ]; then
        gate_refuse "ci-env: $wf indents with a TAB, which YAML forbids and this reader cannot"
        echo "   follow. A file nobody could parse is not a file with nothing in it." >&2
        return 2
    fi
    set +e
    awk '
        /^[ ]*#/ { next }
        {
            line = $0
            sub(/[ ]*$/, "", line)
            if (line == "") next
            indent = match(line, /[^ ]/) - 1
            if (in_env && indent <= env_indent) in_env = 0
            if (line ~ /^[ ]*env:[ ]*$/) {
                in_env = 1
                env_indent = indent
                seen_env = 1
                next
            }
            if (in_env && indent > env_indent) {
                key = line
                sub(/^[ ]*/, "", key)
                if (key ~ /^[A-Za-z_][A-Za-z0-9_]*[ ]*:/) {
                    sub(/[ ]*:.*$/, "", key)
                    print key
                }
            }
        }
        END { exit seen_env ? 0 : 3 }
    ' "$wf"
    rc=$?
    set -e
    if [ "$rc" = "3" ]; then
        gate_refuse "ci-env: $wf holds no \`env:\` map at all — this census reads the keys under"
        echo "   the workflow's env maps, and a workflow it cannot find one in is one it" >&2
        echo "   cannot answer about. Could-not-look, not a finding." >&2
        return 2
    fi
    [ "$rc" = "0" ] || return 2
    return 0
}

# docs_ci_env_entries <workflow-file> — `<line>\t<key>\t<value>` for every
# key under any `env:` map, by the same indentation parse as
# `docs_ci_env_keys` (run that one first: it owns the could-not-look refusals).
# The value is the scalar after the colon with a trailing ` #` comment and one
# layer of quotes taken off — enough to tell `""` from a value, which is the
# only question this leg asks of it.
docs_ci_env_entries() {
    awk '
        /^[ ]*#/ { next }
        {
            line = $0
            sub(/[ ]*$/, "", line)
            if (line == "") next
            indent = match(line, /[^ ]/) - 1
            if (in_env && indent <= env_indent) in_env = 0
            if (line ~ /^[ ]*env:[ ]*$/) {
                in_env = 1
                env_indent = indent
                next
            }
            if (in_env && indent > env_indent) {
                key = line
                sub(/^[ ]*/, "", key)
                if (key ~ /^[A-Za-z_][A-Za-z0-9_]*[ ]*:/) {
                    value = key
                    sub(/[ ]*:.*$/, "", key)
                    sub(/^[^:]*:[ ]*/, "", value)
                    sub(/[ ]+#.*$/, "", value)
                    if (value ~ /^".*"$/ || value ~ /^\047.*\047$/) value = substr(value, 2, length(value) - 2)
                    printf "%d\t%s\t%s\n", NR, key, value
                }
            }
        }
    ' "$1"
}

# docs_ci_env_population <readers> <test-settings> <example> — `R <name>` for
# every environment read and `P <name>` for every population member; exit 2
# when a reader does not parse.
docs_ci_env_population() {
    command -v python3 >/dev/null 2>&1 || {
        gate_refuse "ci-env: no python3 on PATH — the reader census parses the settings"
        return 2
    }
    python3 - "$1" "$2" "$3" <<'PY'
import ast
import os
import sys

readers, test_settings, example = sys.argv[1:4]
UNKNOWN = object()


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return UNKNOWN


def read_call(node):
    target = node.func
    if not isinstance(target, ast.Attribute):
        return None, UNKNOWN
    base = target.value
    is_env = isinstance(base, ast.Name) and base.id == "env"
    is_getenv = isinstance(base, ast.Name) and base.id == "os" and target.attr == "getenv"
    is_get = isinstance(base, ast.Attribute) and base.attr == "environ" and target.attr == "get"
    if not (is_env or is_getenv or is_get):
        return None, UNKNOWN
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None, UNKNOWN
    name = node.args[0].value
    if not isinstance(name, str):
        return None, UNKNOWN
    for keyword in node.keywords:
        if keyword.arg == "default":
            return name, literal(keyword.value)
    if len(node.args) > 1:
        return name, literal(node.args[1])
    return name, UNKNOWN


paths = []
if os.path.isfile(readers):
    paths = [readers]
else:
    for top, _dirs, files in os.walk(readers):
        paths.extend(os.path.join(top, f) for f in files if f.endswith(".py"))
skip = os.path.normpath(test_settings)
found = {}
for path in sorted(paths):
    if os.path.normpath(path) == skip:
        continue
    try:
        with open(path) as handle:
            tree = ast.parse(handle.read(), filename=path)
    except SyntaxError as error:
        print(f"!! ci-env: {path} does not parse ({error.msg}, line {error.lineno})", file=sys.stderr)
        sys.exit(2)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name, default = read_call(node)
            if name is not None:
                found.setdefault(name, default)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "environ"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            found.setdefault(node.slice.value, UNKNOWN)

values = {}
with open(example) as handle:
    for line in handle.read().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")


def is_default(value, default):
    if default is UNKNOWN:
        return False
    if isinstance(default, bool):
        truthy = value.lower() in {"1", "true", "yes", "on"}
        falsy = value.lower() in {"0", "false", "no", "off"}
        return truthy if default else falsy
    if isinstance(default, (int, float)):
        try:
            return float(value) == float(default)
        except ValueError:
            return False
    if isinstance(default, (list, tuple)):
        return value == ",".join(str(item) for item in default)
    if default is None:
        return False
    return value == str(default)


for name in sorted(found):
    print(f"R {name}")
for name in sorted(found):
    value = values.get(name, "")
    if value and not is_default(value, found[name]):
        print(f"P {name}")
PY
}

docs_ci_env_leg() {
    local readers=${1:-$DOCS_CI_ENV_READERS}
    local wfs=${2:-$DOCS_CI_ENV_WORKFLOWS}
    local example=${3:-$DOCS_CI_ENV_EXAMPLE}
    local test_settings=${4:-$DOCS_CI_ENV_TEST_SETTINGS}
    local pop keys pinned bad name n nread entries tline wlines wf census rc

    if [ ! -e "$readers" ]; then
        gate_refuse "ci-env: $readers is not in this tree — the population is derived from it"
        return 2
    fi
    if [ ! -f "$example" ]; then
        gate_refuse "ci-env: $example is not in this tree — the population's second half is the"
        echo "   development stack's own values, and no other file carries them." >&2
        return 2
    fi

    pop=$(mktemp "${TMPDIR:-/tmp}/djb-cienv-pop.XXXXXX") || return 2
    set +e
    docs_ci_env_population "$readers" "$test_settings" "$example" >"${pop}.all"
    rc=$?
    set -e
    if [ "$rc" != "0" ]; then
        rm -f "$pop" "${pop}.all"
        return 2
    fi
    sed -n 's/^R //p' "${pop}.all" >"${pop}.read"
    sed -n 's/^P //p' "${pop}.all" >"$pop"
    nread=$(wc -l <"${pop}.read" | tr -d ' ')
    n=$(wc -l <"$pop" | tr -d ' ')
    if [ "${n:-0}" -eq 0 ]; then
        gate_refuse "ci-env: the population is EMPTY — $readers read $nread name(s) and $example"
        echo "   gives none of them a value that differs from the code's default. A green over" >&2
        echo "   nothing is the one verdict this leg may never print." >&2
        rm -f "$pop" "${pop}.all" "${pop}.read"
        return 2
    fi
    echo "  read: $nread name(s) from the environment under $readers ($test_settings excluded)"
    echo "  population ($n): $(tr '\n' ' ' <"$pop" | sed 's/ $//')"
    echo "  — the reads $example gives a non-empty value that is not the code's default"
    rm -f "${pop}.all"

    census=$(mktemp "${TMPDIR:-/tmp}/djb-cienv-wfs.XXXXXX") || {
        rm -f "$pop" "${pop}.read"
        return 2
    }
    if [ -f "$wfs" ]; then
        printf '%s\n' "$wfs" >"$census"
    elif [ -d "$wfs" ]; then
        for wf in "$wfs"/*.yml "$wfs"/*.yaml; do
            [ -f "$wf" ] || continue
            if grep -qE 'scripts/(check|ci_stack)\.sh' "$wf"; then
                printf '%s\n' "$wf" >>"$census"
            else
                echo "  not censused: $wf runs neither scripts/check.sh nor scripts/ci_stack.sh"
            fi
        done
    fi
    if [ ! -s "$census" ]; then
        echo "  SKIP: no workflow under $wfs runs the stack. A product that runs no GitHub Actions"
        echo "  has no workflow env for this census to read — printed, because a skip nobody"
        echo "  sees reads exactly like a pass."
        rm -f "$pop" "${pop}.read" "$census"
        return 0
    fi

    pinned=""
    if [ -f "$test_settings" ]; then
        while IFS= read -r name; do
            [ -n "$name" ] || continue
            if grep -qE "^${name}[[:space:]]*(:[^=]*)?=" "$test_settings"; then
                pinned="${pinned}${name}"$'\n'
            fi
        done <"${pop}.read"
    else
        echo "  note: $test_settings is not in this tree, so no name is exempt by a pin and"
        echo "        the two-authorities half did not run"
    fi

    rm -f "${pop}.read"

    bad=0
    keys=$(mktemp "${TMPDIR:-/tmp}/djb-cienv-keys.XXXXXX") || {
        rm -f "$pop" "$census"
        return 2
    }
    while IFS= read -r wf; do
        if ! docs_ci_env_keys "$wf" >"$keys"; then
            rm -f "$pop" "$keys" "$census"
            return 2
        fi
        entries=$(docs_ci_env_entries "$wf")
        printf '%s\n' "$entries" | awk -F '\t' 'NF >= 2 && $3 != "" { print $2 }' |
            LC_ALL=C sort -u >"$keys"
        echo "  $wf: $(wc -l <"$keys" | tr -d ' ') supplied key(s) under its env: maps"
        printf '%s\n' "$entries" | awk -F '\t' -v wf="$wf" \
            'NF >= 2 && $3 == "" && $2 ~ /^AWS_/ { printf "  cleared: %s at %s:%s — empty is a pin, not a supply\n", $2, wf, $1 }'

        while IFS= read -r name; do
            [ -n "$name" ] || continue
            grep -qxF "$name" "$keys" && continue
            if grep -qxF "$name" <<<"$pinned"; then
                echo "  exempt: $name is pinned by $test_settings, so a workflow value would be"
                echo "          overridden and misleading — the suite reads the pin"
                continue
            fi
            echo "  VIOLATION  ci-env: $name is read from the environment under $readers and is a key"
            echo "             under no env: map in $wf — $example gives it a value the code's"
            echo "             default is not, so the runner's stack is not the one the settings describe"
            bad=$((bad + 1))
        done <"$pop"

        while IFS= read -r name; do
            [ -n "$name" ] || continue
            grep -qxF "$name" "$keys" || continue
            tline=$(grep -nE "^${name}[[:space:]]*(:[^=]*)?=" "$test_settings" | sed -n '1p' | cut -d: -f1)
            wlines=$(printf '%s\n' "$entries" |
                awk -F '\t' -v k="$name" -v wf="$wf" '$2 == k && $3 != "" { printf "%s%s:%s", sep, wf, $1; sep = ", " }')
            echo "  VIOLATION  ci-env: $name has TWO authorities — $test_settings:${tline:-?} and $wlines."
            echo "             $test_settings pins $name, which $wf also supplies as an env: key — the"
            echo "             pin wins, so the workflow line is inert. The test settings are the one"
            echo "             authority: delete the workflow line"
            bad=$((bad + 1))
        done <<<"$pinned"
    done <"$census"

    rm -f "$pop" "$keys" "$census"
    if [ "$bad" = "0" ]; then
        echo "  ok — every population name is supplied by every censused workflow or pinned by"
        echo "  the test settings, and no name has two authorities"
        echo "  blind spot: KEYS, NOT VALUES — a wrong endpoint is a green census and a red run"
        return 0
    fi
    return 1
}
