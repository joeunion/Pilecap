#!/usr/bin/env bash
# The four `--fast` census bodies that ask a closed question of a DOCUMENT
# rather than of the code: the two extracted from `scripts/publish.sh` so its
# release-time scan and `scripts/check.sh`'s per-rung legs share ONE
# implementation, and the two new ones that had no home at all.
#
#   docs_adr_census <root> <file-list-file>      · publish.sh + check.sh --fast
#   docs_dangling_docs <root> <file-list-file>   · publish.sh + check.sh --fast
#   docs_adr_census_loop / docs_dangling_docs_loop  · check.sh's per-rung bodies
#   docs_loop_names_leg                          · check.sh --fast
#   docs_ci_env_leg                              · check.sh --fast
#
# Sourced by scripts/publish.sh, scripts/check.sh and
# scripts/tests/test_fast_censuses.sh's drive. The two `_loop` bodies also need
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
# contract (`scripts/tests/test_publish.sh` greps it), so it is the default and
# a caller that means something else says so.
DOCS_LEGS_SCOPE_NOUN=${DOCS_LEGS_SCOPE_NOUN:-the artifact}

# THE TWO ADR HOMES, ASSEMBLED RATHER THAN SPELLED. This file SHIPS (bucket
# R3), so a `docs/…` path ending in the markdown suffix written out in full
# here is a POINTER SITE the `dangling-docs` census below then counts — and
# publish.sh's printed "N pointer sites read" line would move by the very act
# of extracting the leg that prints it, which is the one thing the extraction
# may not do. Halves no pattern can join, the discipline archaeology_lib.sh
# uses for the same reason.
_docs_legs_d="docs/product/"
DOCS_ADR_HOMES=${DOCS_ADR_HOMES:-"${_docs_legs_d}architecture.md ${_docs_legs_d}adrs-ingredients.md"}
unset _docs_legs_d

# The two greps, in one place. Both are the shapes `publish.sh` has always
# read; neither matches its own text (after the id keyword and after `docs/`
# comes `[`, which is in neither character class), which is why they can be
# spelled here at all.
DOCS_ADR_RE='ADR [a-z0-9]+-[a-z0-9]+'
DOCS_REF_RE='docs/[A-Za-z0-9._/-]+\.md'

# Set by the two scans; the caller prints them. `publish.sh`'s two count lines
# are byte-for-byte the ones it always printed, computed here instead of there.
DOCS_ADR_SITES=0
DOCS_ADR_IDS=0
DOCS_DANGLING_SITES=0

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
# Every `ADR <app>-<n>` id cited by any file in the list must resolve in one of
# the two ADR homes under <root>. Prints one
# `adr-census: <id> resolves nowhere in <noun> — cited in <file>` per finding
# TO STDOUT AND NOTHING ELSE; the caller counts those lines and owns the
# verdict (archaeology_scan_tree's contract, and for its reason: a `$(...)`
# capture would swallow the very lines it is meant to let through).
#
# Sets DOCS_ADR_SITES and DOCS_ADR_IDS. Returns 0 once every file has been
# read, 2 if it could not look — a missing ADR home, homes that name no ids at
# all, or a `grep` that could not read the set. Never 1: a finding is a line,
# not a status, here.
docs_adr_census() {
    local root=$1 list=$2 h homes cited rc line id file
    DOCS_ADR_SITES=0
    DOCS_ADR_IDS=0

    homes=$(mktemp "${TMPDIR:-/tmp}/djb-docs-homes.XXXXXX") || return 2
    for h in $DOCS_ADR_HOMES; do
        if [ ! -f "$root/$h" ]; then
            gate_refuse "adr-census: $h is not in ${DOCS_LEGS_SCOPE_NOUN} — the ADR home does not"
            echo "   ship, so no citation in it can resolve. That is the ruling broken, not a" >&2
            echo "   violation." >&2
            rm -f "$homes"
            return 2
        fi
    done
    for h in $DOCS_ADR_HOMES; do
        grep -hoE "$DOCS_ADR_RE" "$root/$h" || true
    done | LC_ALL=C sort -u >"$homes"
    if [ ! -s "$homes" ]; then
        gate_refuse "adr-census: the ADR homes named no ids at all — the grammar this leg reads"
        echo "   is the id keyword followed by <app>-<n>, and a home with none of them is this" >&2
        echo "   leg looking at the wrong thing." >&2
        rm -f "$homes"
        return 2
    fi
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
        file=${line%%:*}
        if ! grep -qxF "$id" "$homes"; then
            printf 'adr-census: %s resolves nowhere in %s — cited in %s\n' \
                "$id" "$DOCS_LEGS_SCOPE_NOUN" "$file"
        fi
    done <"$cited"
    rm -f "$homes" "$cited"
    return 0
}

# docs_dangling_docs <root> <file-list-file>
#
# INVARIANT 2'S SIBLING, FOR ORDINARY POINTERS. Trimming is exactly the
# operation that turns a live citation into a dead one, and a first builder
# reading a plan path in a docstring finds nothing there and cannot tell
# whether the claim was ever true. Closed question, discoverable population:
# every markdown path under `docs/` spelled anywhere in the file set must exist
# under <root>.
#
# Same output contract, same exit semantics, and sets DOCS_DANGLING_SITES.
docs_dangling_docs() {
    local root=$1 list=$2 refs rc line ref file
    DOCS_DANGLING_SITES=0

    if ! docs_legs_read_list "$root" "$list"; then
        gate_refuse "dangling-docs: the file list could not be read — nothing was scanned"
        return 2
    fi
    refs=$(mktemp "${TMPDIR:-/tmp}/djb-docs-refs.XXXXXX") || return 2
    if [ "${#DOCS_LEGS_FILES[@]}" -gt 0 ]; then
        set +e
        (cd "$root" && grep -HIoE "$DOCS_REF_RE" -- "${DOCS_LEGS_FILES[@]}") >"${refs}.raw" 2>/dev/null
        rc=$?
        set -e
        if [ "$rc" -gt 1 ]; then
            gate_refuse "dangling-docs: the pointer scan could not read ${DOCS_LEGS_SCOPE_NOUN}"
            echo "   (grep exited $rc). A tree nobody looked at is not a clean tree." >&2
            rm -f "$refs" "${refs}.raw"
            return 2
        fi
        sed 's|^\./||' "${refs}.raw" | LC_ALL=C sort -u >"$refs"
        rm -f "${refs}.raw"
    else
        : >"$refs"
    fi

    DOCS_DANGLING_SITES=$(wc -l <"$refs" | tr -d ' ')
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        ref=${line#*:}
        file=${line%%:*}
        [ -f "$root/$ref" ] && continue
        printf 'dangling-docs: %s does not exist in %s — spelled in %s\n' \
            "$ref" "$DOCS_LEGS_SCOPE_NOUN" "$file"
    done <"$refs"
    rm -f "$refs"
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
    set -e
    rm -f "$DOCS_LEGS_LIST"
    if [ "$rc" = "2" ]; then
        rm -f "$out"
        return 2
    fi

    echo "  $DOCS_ADR_SITES citation site(s) in the changed set · $DOCS_ADR_IDS ids resolvable in the two homes"
    bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "  VIOLATION  $line"
        bad=$((bad + 1))
    done <"$out"
    rm -f "$out"
    if [ "$bad" = "0" ]; then
        echo "  ok — every ADR id the active rung cites resolves in one of the two homes"
        echo "  (publish.sh's whole-artifact scan stays the belt: a dead citation in a file"
        echo "  the active rung did not touch is invisible here by design)"
        return 0
    fi
    return 1
}

docs_dangling_docs_loop() {
    local rc bad out line
    DOCS_LEGS_SCOPE_NOUN="the tree"
    _docs_legs_changed || return 2
    if [ "$DOCS_LEGS_SHIP_N" = "0" ]; then
        rm -f "$DOCS_LEGS_LIST"
        echo "  NOTHING TO SCAN: the active rung changed no bucket-SHIP file."
        return 0
    fi

    out=$(mktemp "${TMPDIR:-/tmp}/djb-docs-dang-out.XXXXXX") || {
        rm -f "$DOCS_LEGS_LIST"
        return 2
    }
    set +e
    docs_dangling_docs "$PWD" "$DOCS_LEGS_LIST" >"$out"
    rc=$?
    set -e
    rm -f "$DOCS_LEGS_LIST"
    if [ "$rc" = "2" ]; then
        rm -f "$out"
        return 2
    fi

    echo "  $DOCS_DANGLING_SITES pointer site(s) in the changed set"
    bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "  VIOLATION  $line"
        bad=$((bad + 1))
    done <"$out"
    rm -f "$out"
    if [ "$bad" = "0" ]; then
        echo "  ok — every docs pointer the active rung spells exists in this tree"
        return 0
    fi
    return 1
}

# --------------------------------------------------------------------------
# docs_loop_names_leg — the `LOOP_*` name census.
#
# WHAT IT ASKS, and why the naive form of the question is worse than no
# question at all. A fork of this platform that kept a `check.sh` refusal block
# reading a `LOOP_*` variable the platform no longer sets does not fail at the
# line that reads it: it fails minutes later, at the pytest banner, under
# `set -u`, with an unbound-variable message naming a variable nobody has heard
# of. The consumer paid four `--loop` runs finding that out.
#
# THE INSTRUMENT THAT WAS PROPOSED FOR IT IS FALSE ON THIS TREE, measured: the
# two-file difference between the LOOP_* names in `scripts/loop_tier.sh` and
# those in `scripts/check.sh` returns 23 names here, every one of them a
# variable `check.sh` legitimately assigns itself. A census that reds a correct
# tree teaches its reader to ignore it.
#
# THE HONEST FORM, and the whole of it: the names `check.sh` READS minus the
# names ANY OF THE THREE FILES ASSIGNS. `check.sh` is the only reader because
# it is the only file whose `set -u` death is the symptom; the three assigners
# are the three files a `--loop` sources into one shell — `check.sh` itself,
# `scripts/loop_tier.sh` and `scripts/gate_ledger.sh` — and they are NAMED
# here, in the leg's own text, because a fourth sourced library that set a
# `LOOP_*` name would red this census honestly until it was added to the list.
#
# WHAT A "READ" IS, and the one exclusion, which is the difference between an
# honest empty and a dishonest one. `${NAME:-default}` and `${NAME-default}`
# CANNOT die under `set -u` — the default is what the shell substitutes when
# the name is unset, so a defaulted read is exactly the shape this census
# exists to permit. `check.sh` has one name it reads ONLY that way today —
# `LOOP_LEDGER_CENSUS`, which nothing anywhere in this tree assigns — and the
# plan that commissioned this leg predicted it would be found assigned by
# `gate_ledger.sh`. It is not. Excluding defaulted reads is therefore
# load-bearing rather than tidy: without it this census reds the platform's own
# tree on a line that is correct.
#
# DECLARED BLIND SPOT: a name read only with a default is invisible here, which
# is the paragraph above read the other way — this leg proves a `--loop` cannot
# die of an unbound `LOOP_*`, never that every `LOOP_*` is meaningful.
#
# Exit: 0 every read name is assigned · 1 one is not, each named with the three
# files that should set it · 2 could-not-look.
# --------------------------------------------------------------------------
DOCS_LOOP_NAMES_READER=${DOCS_LOOP_NAMES_READER:-scripts/check.sh}
DOCS_LOOP_NAMES_ASSIGNERS=${DOCS_LOOP_NAMES_ASSIGNERS:-"scripts/check.sh scripts/loop_tier.sh scripts/gate_ledger.sh"}

docs_loop_names_leg() {
    local reader=${1:-$DOCS_LOOP_NAMES_READER}
    local assigners=${2:-$DOCS_LOOP_NAMES_ASSIGNERS}
    local f read_f asg_f bad n name

    if [ ! -f "$reader" ]; then
        gate_refuse "loop-names: $reader is not in this tree — the census reads it and nothing else"
        return 2
    fi
    for f in $assigners; do
        if [ ! -f "$f" ]; then
            gate_refuse "loop-names: $f is not in this tree — one of the files that may assign a"
            echo "   LOOP_* name is missing, so READ − ASSIGNED would name every read name as a" >&2
            echo "   violation. Could-not-look, not a finding." >&2
            return 2
        fi
    done

    read_f=$(mktemp "${TMPDIR:-/tmp}/djb-loopnames-read.XXXXXX") || return 2
    asg_f=$(mktemp "${TMPDIR:-/tmp}/djb-loopnames-asg.XXXXXX") || return 2

    # THE READ SET, in two passes because the two syntaxes carry different
    # information. An UNBRACED `$LOOP_X` can never carry a default, so every
    # one is a read that can die. A BRACED one can, so the character right
    # after the name is read too and the `-` forms are dropped: `${LOOP_X:-y}`
    # and `${LOOP_X-y}` substitute rather than die. Doing this in ONE grep
    # would mis-drop `"$LOOP_X-suffix"`, an unbraced read followed by a literal
    # hyphen, which is a read that dies.
    {
        grep -ohE '\$LOOP_[A-Z0-9_]+' "$reader" | sed -E 's/^\$//' || true
        grep -ohE '\$\{LOOP_[A-Z0-9_]+(:?[-+])?' "$reader" |
            grep -vE '[-+]$' |
            sed -E 's/^\$\{//' || true
    } | LC_ALL=C sort -u >"$read_f"

    # THE ASSIGNED SET: `LOOP_X=` anywhere (a bare assignment, a `local`, an
    # `export`, a `declare`) and `for LOOP_X in` — a loop variable is assigned
    # by the loop, which the naive instrument's residual names were the proof
    # of.
    {
        for f in $assigners; do
            grep -ohE 'LOOP_[A-Z0-9_]+=' "$f" | sed 's/=$//' || true
            grep -ohE 'for[[:space:]]+LOOP_[A-Z0-9_]+[[:space:]]+in' "$f" |
                sed -E 's/^for[[:space:]]+//; s/[[:space:]]+in$//' || true
        done
    } | LC_ALL=C sort -u >"$asg_f"

    n=$(wc -l <"$read_f" | tr -d ' ')
    if [ "${n:-0}" -eq 0 ]; then
        gate_refuse "loop-names: $reader reads no LOOP_* name at all — this census is looking at"
        echo "   the wrong file, or at a shape it no longer recognises. A grep that found" >&2
        echo "   nothing is not a tree with nothing in it." >&2
        rm -f "$read_f" "$asg_f"
        return 2
    fi

    echo "  $n LOOP_* name(s) read by $reader, defaulted reads excluded (they cannot die"
    echo "  under set -u) · $(wc -l <"$asg_f" | tr -d ' ') assigned across: $assigners"

    bad=0
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        echo "  VIOLATION  loop-names: $name is read by $reader and assigned by none of:"
        echo "             $assigners"
        bad=$((bad + 1))
    done < <(LC_ALL=C comm -23 "$read_f" "$asg_f")
    rm -f "$read_f" "$asg_f"

    if [ "$bad" = "0" ]; then
        echo "  ok — READ − ASSIGNED is empty: no --loop can die at the pytest banner on an"
        echo "  unbound LOOP_* name"
        return 0
    fi
    return 1
}

# --------------------------------------------------------------------------
# docs_ci_env_leg — the `ci-env` census, tri-state.
#
# WHAT IT ASKS: the runner's stack is the one the settings describe. One CI run
# ended `27 failed, 3283 passed, 9 skipped, 110 errors` and all 110 errors were
# botocore's no-credentials exception — boto3 finding no credentials anywhere,
# in the one environment that had a healthy object store on its own port,
# because the workflow's `env:` block named none of the keys
# `config/settings/base.py` reads. 39 of 40 runs red and nothing said why.
#
# THE POPULATION IS DERIVED FROM TWO FILES, and each half is load-bearing:
#
#   1. `config/settings/base.py` — every `AWS_[A-Z0-9_]+` read from the
#      environment through `env.str(...)`. THE DIGIT IS IN THE CHARACTER CLASS
#      and that is not a detail: `AWS_[A-Z_]+` stops dead at `AWS_S` and is
#      blind to every one of the `AWS_S3_*` names — measured on this tree,
#      where the digit-blind grep yields the bogus token `AWS_S` and four real
#      names vanish. `env.bool`/`env.int` reads are deliberately NOT in the
#      population: their default is a typed value, and "is the environment's
#      text the same as that default" is a question about Python types that a
#      shell census has no business answering.
#   2. `.env.example` — of those, the names it gives a NON-EMPTY value. That
#      file is what a laptop copies, and `base.py`'s `default=""` idiom means
#      "unset is off". A name the development stack leaves empty is off on a
#      laptop and off on a runner, and there is nothing to census; a name it
#      fills is a value the compose stack needs, and CI runs the same compose
#      stack.
#
# AND ONE SUBTRACTION, which is the mirror lens: a key `config/settings/test.py`
# PINS is inert whatever the workflow supplies — the suite reads the pin. So a
# pinned key is not required in the workflow, AND a pin of a key the workflow
# DOES supply is a finding of its own: the `env:` line looks like it is doing
# something and is doing nothing. `test.py` pins one bucket name today and the
# workflow deliberately does not supply it, which is the negative.
#
# DECLARED BLIND SPOTS, printed by the leg itself on every clean run:
#   · KEYS, NOT VALUES. A wrong endpoint port is a green census and a red run.
#   · A product whose runner takes credentials from a secret store the YAML
#     never names would red here wrongly; the escape is that ANY value
#     satisfies the census, a `secrets.` expression included, and a product
#     that needs more records a `# rule` valve with its reason.
#   · AWS NAMES ONLY. Another organ the tests dial (a search key, a workflow
#     engine's address) is not censused; the trigger is the next
#     credentials-shaped red for one of them.
#
# Exit: 0 clean, or the workflow file is absent (a product without Actions —
# PRINTED, never silent) · 1 a name is missing from every `env:` map, or a
# supplied name is pinned by the test settings · 2 could-not-look.
# --------------------------------------------------------------------------
DOCS_CI_ENV_SETTINGS=${DOCS_CI_ENV_SETTINGS:-config/settings/base.py}
DOCS_CI_ENV_TEST_SETTINGS=${DOCS_CI_ENV_TEST_SETTINGS:-config/settings/test.py}
DOCS_CI_ENV_EXAMPLE=${DOCS_CI_ENV_EXAMPLE:-.env.example}
_docs_legs_wf=".github/workflows/"
DOCS_CI_ENV_WORKFLOW=${DOCS_CI_ENV_WORKFLOW:-${_docs_legs_wf}ci.yml}
unset _docs_legs_wf

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

docs_ci_env_leg() {
    local settings=${1:-$DOCS_CI_ENV_SETTINGS}
    local wf=${2:-$DOCS_CI_ENV_WORKFLOW}
    local example=${3:-$DOCS_CI_ENV_EXAMPLE}
    local test_settings=${4:-$DOCS_CI_ENV_TEST_SETTINGS}
    local pop keys pinned bad name n

    if [ ! -f "$settings" ]; then
        gate_refuse "ci-env: $settings is not in this tree — the population is derived from it"
        return 2
    fi
    if [ ! -f "$example" ]; then
        gate_refuse "ci-env: $example is not in this tree — the census's second half is the"
        echo "   development stack's own values, and there is no other file that carries them." >&2
        return 2
    fi

    pop=$(mktemp "${TMPDIR:-/tmp}/djb-cienv-pop.XXXXXX") || return 2
    # THE ENVIRONMENT READS, string-valued, DIGIT CLASS INCLUDED.
    {
        grep -ohE 'env\.str\("AWS_[A-Z0-9_]+"' "$settings" |
            sed -E 's/^env\.str\("//; s/"$//' || true
    } | LC_ALL=C sort -u >"${pop}.read"
    # NARROWED TO THE ONES THE DEVELOPMENT STACK ACTUALLY SUPPLIES.
    : >"$pop"
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        if grep -qE "^${name}=.+$" "$example"; then
            printf '%s\n' "$name" >>"$pop"
        fi
    done <"${pop}.read"
    n=$(wc -l <"$pop" | tr -d ' ')
    if [ "${n:-0}" -eq 0 ]; then
        gate_refuse "ci-env: the population is EMPTY — $settings named no string-valued AWS_ read"
        echo "   that $example gives a value. A census with nothing in its population is a" >&2
        echo "   green over nothing, which is the one verdict this leg may never print." >&2
        rm -f "$pop" "${pop}.read"
        return 2
    fi
    echo "  population ($n): $(tr '\n' ' ' <"$pop" | sed 's/ $//')"
    echo "  derived from $settings's string-valued environment reads — THE DIGIT IS IN THE"
    echo "  CLASS: AWS_[A-Z_]+ stops at AWS_S and is blind to every AWS_S3_* name — then"
    echo "  narrowed to the names $example gives a non-empty value"
    echo "  read but out of the population: $(LC_ALL=C comm -23 "${pop}.read" "$pop" | tr '\n' ' ' | sed 's/ $//')"
    rm -f "${pop}.read"

    if [ ! -f "$wf" ]; then
        echo "  SKIP: $wf is not in this tree. A product that runs no GitHub Actions has no"
        echo "  workflow env for this census to read — printed rather than silent, because a"
        echo "  skip nobody sees reads exactly like a pass."
        rm -f "$pop"
        return 0
    fi

    keys=$(mktemp "${TMPDIR:-/tmp}/djb-cienv-keys.XXXXXX") || {
        rm -f "$pop"
        return 2
    }
    if ! docs_ci_env_keys "$wf" >"$keys"; then
        rm -f "$pop" "$keys"
        return 2
    fi
    echo "  $(wc -l <"$keys" | tr -d ' ') key(s) under the env: maps of $wf (any level; any value"
    echo "  satisfies the census — this leg reads KEYS, never values)"

    bad=0
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        if grep -qxF "$name" "$keys"; then
            continue
        fi
        # A key the TEST SETTINGS pin is inert whatever the workflow says, so
        # its absence is correct rather than missing — and it is said out loud,
        # because a name silently dropped from a population is how a census
        # stops looking.
        if [ -f "$test_settings" ] && grep -qE "^${name}[[:space:]]*=" "$test_settings"; then
            echo "  exempt: $name is pinned by $test_settings, so a workflow value would be"
            echo "          overridden and misleading — the suite reads the pin"
            continue
        fi
        echo "  VIOLATION  ci-env: $name is read from the environment by $settings and is a key"
        echo "             under no env: map in $wf — the runner's stack is not the one the"
        echo "             settings describe (this is the no-credentials shape)"
        bad=$((bad + 1))
    done <"$pop"

    # THE MIRROR LENS (the second half, and the one a green first half hides):
    # a key the workflow DOES supply that the test settings then pin is an
    # `env:` line doing nothing at all, while every criterion about the block
    # passes.
    if [ -f "$test_settings" ]; then
        pinned=$({ grep -ohE '^AWS_[A-Z0-9_]+[[:space:]]*=' "$test_settings" || true; } |
            sed -E 's/[[:space:]]*=$//' | LC_ALL=C sort -u)
        while IFS= read -r name; do
            [ -n "$name" ] || continue
            if grep -qxF "$name" "$keys"; then
                echo "  VIOLATION  ci-env: $test_settings pins $name, which $wf also supplies as an"
                echo "             env: key — the pin wins, so the workflow line is inert and the"
                echo "             runner is not dialling what the block says it dials"
                bad=$((bad + 1))
            fi
        done <<<"$pinned"
    else
        echo "  note: $test_settings is not in this tree, so the override half of this census"
        echo "        did not run — a pin that makes a workflow key inert would be invisible"
    fi

    rm -f "$pop" "$keys"
    if [ "$bad" = "0" ]; then
        echo "  ok — every name the settings read from the environment is a key the workflow"
        echo "  supplies, and no pin makes one of them inert"
        echo "  blind spot: KEYS, NOT VALUES — a wrong endpoint or a stale credential is a"
        echo "  green census and a red run; the run is the belt. AWS names only."
        return 0
    fi
    return 1
}
