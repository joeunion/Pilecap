#!/usr/bin/env bash
# The archaeology census + the publication bucket rules, extracted so
# `scripts/publish.sh`'s full-artifact scan and `scripts/check.sh`'s per-rung
# `archaeology` leg share ONE implementation instead of two that agree today
# and drift tomorrow.
# Sourced by scripts/publish.sh, scripts/check.sh and
# quality/tests/test_fe_leg.py / quality/tests/test_publish.py's worlds.
# BASH ONLY, for the reason gate_ledger.sh states: sourced into an interactive
# zsh, `local path` ties to $PATH and every helper dies silently.
#
# NOT EXECUTABLE, AND THAT IS THE DECLARATION, not an oversight: this file
# reports no verdict of its own — it hands a classification and a scan result
# to whoever sourced it, and the caller owns the exit status. A library beside
# secrets_scan.sh and db.sh, not an instrument beside them.
#
# ---------------------------------------------------------------------------
# WHY IT EXISTS. `scripts/publish.sh` used to carry `rules_for`,
# `bucket_for_rule` and the six archaeology-census patterns as its own
# functions, read by nothing else. The per-rung `archaeology` leg in
# `scripts/check.sh` needs the identical classification — a changed
# file is in scope for the leg only when it would SHIP (bucket SHIP), because
# a PM ledger row citing a finding id or a rung token is exactly the vocabulary
# a SKELETON file is FOR, and the leg reddening on one would be the bucket
# rules' whole argument ignored one door over. Two copies of "is this file
# SHIP" is the drift the whole census discipline exists to refuse, so there is
# now one copy, sourced twice.
#
# THE TALLY IS DERIVED, NOT LISTED. `publish.sh` used to
# carry `RULE_IDS="R1 R2 … R10"` as a typed constant for its own printed
# per-rule table — a second population that had to be kept in step with
# `bucket_for_rule`'s `case` by hand, and a rule added to one and not the
# other is a SILENT missing row: `bucket_for_rule` still classifies it, the
# printed table just never shows it, and nothing here or in `test_publish.sh`
# would notice. `archaeology_rule_ids` below reads the ids straight out of
# `bucket_for_rule`'s own `declare -f` text, so a rule id can only ever be
# added or removed in the one place that also decides its bucket.
# ---------------------------------------------------------------------------

# THE REFUSAL SEAM — scripts/gate_refuse.sh, sourced by this library's own
# directory and guarded against a second source. The census's two could-not-look
# headlines go through `gate_refuse` so the archaeology leg's banner can name which
# scan could not read what.
# shellcheck source=scripts/gate_refuse.sh
if [ -z "${GATE_REFUSE_SOURCED:-}" ]; then
    case "${BASH_SOURCE[0]:-}" in
    */*) . "${BASH_SOURCE[0]%/*}/gate_refuse.sh" ;;
    *) . scripts/gate_refuse.sh ;;
    esac
fi

# --- the publication bucket rules (docs/product/publication-manifest.md) ----
#
# `rules_for <path>` echoes every rule id the path matches. Exactly one is
# the contract; the caller enforces it (publish.sh's census leg). The rules
# are written to be mutually exclusive BY CONSTRUCTION, and the double-match
# refusal there is what proves they still are.
rules_for() {
    local p=$1 hit="" _cy="" _br=""
    case "$p" in
    apps/* | config/* | manage.py | pilecap/*) hit="$hit R1" ;;
    esac
    case "$p" in
    quality/* | docs/product/instruments.md) hit="$hit R2" ;;
    esac
    # R12 BEFORE R3's GLOB, IN ONE `case` WITH TWO ARMS — the R8S/R8 shape
    # exactly, and for its reason: `case` takes the FIRST matching pattern, so
    # the three measured files are mutually exclusive with the instruments glob
    # BY CONSTRUCTION rather than by care, and the census's double-match refusal
    # still proves it. Split them into two blocks and every R12 path
    # double-matches into exit 2.
    #
    # THE THREE PATHS ARE SPELLED, and that is the one hand list in this file.
    # It is legal here because the rung that wrote it named what RE-DERIVES it:
    # `test_r12_is_the_measured_files_the_readers_default_to` in quality/tests/test_archaeology.py
    # greps the three readers' own defaults — `DJB_GATE_DURATIONS_PATH:-` and
    # `DJB_GATE_MEMBER_DURATIONS:-` in scripts/check.sh, `LOOP_SCOPE_MAP_PATH=`
    # in quality/djb/scope.py — and reds when the two sets differ, so a fourth
    # measured file with no row here is a red rather than a silent ship.
    case "$p" in
    scripts/test_impact.json | scripts/pytest_durations.json | scripts/gate_member_durations.json) hit="$hit R12" ;;
    # R14 — the platform's own proofs; a second arm before the glob, for R12's reason.
    .github/workflows/proof-from-zero.yml | .github/workflows/nightly-proof.yml | .github/workflows/mirror-images.yml) hit="$hit R14" ;;
    scripts/* | deploy/* | perf/* | compose.yaml | compose/* | Dockerfile | .dockerignore | .devcontainer/* | .github/*) hit="$hit R3" ;;
    esac
    case "$p" in
    pyproject.toml | uv.lock | .python-version | .env.example | .gitignore | .editorconfig | .gitattributes | .secrets.baseline | vendor/* | templates/*) hit="$hit R4" ;;
    esac
    case "$p" in
    .claude/skills/* | .claude/agents/* | CLAUDE.md | README.md | docs/runbooks/* | docs/standards.md) hit="$hit R5" ;;
    esac
    case "$p" in
    TEMPLATE_VERSION | CHANGELOG.md) hit="$hit R6" ;;
    esac
    case "$p" in
    docs/product/north-star.md | docs/product/queue.md | docs/product/queue-detail.md | docs/product/readouts.md | docs/product/misses.md | docs/product/in-flight.md | docs/product/goal-posts.md | docs/product/design-agreements.md | docs/product/pilot-readiness.md | docs/product/rep-day.md | docs/product/threat-model.md) hit="$hit R7" ;;
    esac
    # R8S BEFORE R8's GLOB. `case` takes the FIRST matching pattern, so the two
    # format-teaching files under cycles/ are mutually exclusive with the
    # archaeology glob BY CONSTRUCTION rather than by care — the same property
    # every other rule pair here has, and the double-match refusal still
    # proves it. They ship because four shipped files call cycles/ the
    # contract's home, and a home with no example and no README is a pointer
    # at an empty room.
    #
    # THE TWO PATHS ARE ASSEMBLED, NEVER SPELLED — R9's dated-handoff clause
    # is a GLOB, not a filename. This file ships (R3) and the `dangling-docs`
    # leg counts `docs/**.md` strings wherever they appear, INCLUDING inside
    # this file when it runs against somebody else's tree; naming the pieces
    # costs the fixture nothing.
    #
    # ONE `case`, TWO ARMS — not two blocks. Every other rule here is its own
    # block because the rules are disjoint across blocks and `hit` accumulates;
    # these two OVERLAP by design, and only a shared block's first-match rule
    # separates them. Split them and every R8S path double-matches into exit 2.
    # The briefs directory takes the same shape: its README ships, the briefs are the build's archaeology.
    _cy=docs/product/cycles
    _br=docs/product/briefs
    case "$p" in
    "$_cy"/EXAMPLE-cycle-plan.md | "$_cy"/README.md | "$_br"/README.md) hit="$hit R8S" ;;
    "$_cy"/* | "$_br"/* | docs/product/archive/* | docs/product/retro/* | docs/product/drafts/* | docs/product/proposals/* | docs/product/surveys/* | docs/product/reports/* | docs/product/pm-handoff-*.md) hit="$hit R8" ;;
    esac
    # R9's LAST TWO ARMS ARE GLOBS — the design directory, the pattern book's home, and the
    # ADR directory, the decision log (one file per id).
    # R8's clause names the class, never the instance: the book ships, and its
    # drawer beside it is the product's and the template never tracks it, so
    # there is nothing here for a glob to swallow that a filename would have
    # kept out, and one glob cannot double-match. A NEW directory under
    # docs/product/ is still unplaced (exit 2) until somebody decides it.
    case "$p" in
    docs/product/adrs-ingredients.md | docs/product/api-editorial-standard.md | docs/product/architecture.md | docs/product/build-contract.md | docs/product/operating-protocol.md | docs/product/partition-closure.md | docs/product/scale-envelope.md | docs/product/publication-manifest.md | docs/product/design/* | docs/product/adrs/*) hit="$hit R9" ;;
    esac
    case "$p" in
    docs/product/skeletons/*) hit="$hit R10" ;;
    esac
    # R11 — THE CLIENT LAYER. It ships for the same reason `apps/example` does:
    # a rule that never fired anywhere is decoration, and the standing subjects
    # of every frontend rule (the byte-pin, SurfaceState in anger, the rendered
    # census's live scan) need a tree to be proven against. One glob, because
    # the whole directory is one artefact — the scaffold, its lockfile, its
    # committed document and the generated client the pin compares.
    case "$p" in
    frontend/*) hit="$hit R11" ;;
    esac
    # R13 — THE SDK REFERENCE, generated from the facade and the goldens; the
    # one place a product developer reads. One glob: the directory is one artefact.
    case "$p" in
    docs/sdk/*) hit="$hit R13" ;;
    esac
    # TWO WAYS TO READ ONE ANSWER, AND THEY ARE THE SAME ANSWER. `$(rules_for
    # …)` is the obvious one and it FORKS: `scripts/divergence_census.sh`
    # classifies every path in the tree — 1,571 of them here — and spent four
    # of its five seconds in command substitution alone. A caller in a hot loop
    # therefore calls `rules_for "$p" >/dev/null` and reads `$RULES_FOR`, which
    # is set from the same variable the printf writes, on the same line, so the
    # two cannot disagree. It is one assignment rather than a second reader.
    RULES_FOR=${hit# }
    printf '%s' "$RULES_FOR"
}

bucket_for_rule() {
    case "$1" in
    R1 | R2 | R3 | R4 | R5 | R6 | R9 | R11 | R13) printf 'SHIP' ;;
    # R8S: the two format-teaching files inside an otherwise-trimmed directory.
    # They are FORMAT, not archaeology — the plan template and the directory's
    # own contract — and four shipped files send a first PM there.
    R8S) printf 'SHIP' ;;
    R7) printf 'SKELETON' ;;
    # R8's last clause is a GLOB, not the dated filename it replaced, and that
    # is load-bearing rather than tidy: leg `dangling-docs` counts
    # `docs/**.md` strings wherever they appear — a rule that SPELLED a
    # trimmed path would make this file cite a pointer its own artifact
    # cannot resolve. A marker spelled in the thing that defines the marker
    # is a phantom, and the fix is always to name the class rather than the
    # instance.
    R8) printf 'TRIM' ;;
    # R12 — THE MEASURED FILES. Three JSON files this platform's own boxes
    # wrote about this platform's own suite: the test-impact map (a test list
    # and the tree it was generated from), the pytest timings and the gate
    # members' timings. They are MEASUREMENTS, not instruments, and a
    # measurement of somebody else's suite on somebody else's machine is worse
    # than nothing in a product's tree — it is a claim the product never made
    # and cannot check, keyed on a tree that does not exist there. Every reader
    # already treats ABSENCE as "measure it yourself" and says so on its own
    # line, so trimming costs a consumer one measured run and buys them a
    # clean modify/delete at every future fold. (The alternative — shipping
    # them EMPTY — was rejected: an empty durations file is still a claim about
    # a suite, and it still conflicts with the product's own copy.)
    R12) printf 'TRIM' ;;
    # R14 — the platform proves itself; a product's repository proves the product.
    R14) printf 'TRIM' ;;
    R10) printf 'SKELETON-SOURCE' ;;
    *) printf 'UNKNOWN' ;;
    esac
}

# archaeology_rule_ids — every rule id `bucket_for_rule` classifies, derived
# from its own source text rather than typed as a second list (see the header
# note). `declare -f` reproduces the function's parsed body WITHOUT comments
# (bash strips them at parse time, before the text a function stores is even
# built), so a rule id mentioned only in a comment can never leak in here —
# tested directly: a case arm's trailing `# a comment mentioning R99` does not
# appear in `declare -f`'s output. The natural sort (R8 before R8S before R9,
# R9 before R10) is cosmetic — nothing downstream depends on the order — but
# it is what keeps the printed table reading the way the old typed list did.
archaeology_rule_ids() {
    declare -f bucket_for_rule |
        grep -oE '\bR[0-9]+S?\b' |
        LC_ALL=C sort -u |
        awk '{
            n = $0; sub(/^R/, "", n); suf = 0
            if (n ~ /S$/) { suf = 1; sub(/S$/, "", n) }
            printf "%05d.%d %s\n", n, suf, $0
        }' |
        sort -n |
        cut -d' ' -f2
}

# bucket_for_path <path> — `rules_for` + `bucket_for_rule` composed for one
# path. Echoes the bucket, or `AMBIGUOUS` when the path matched zero or more
# than one rule. `publish.sh`'s own census leg is what actually ENFORCES
# exactly-one-bucket (exit 2, naming the path) — this composition exists for
# callers, like the `archaeology` --loop leg, that only need to ask "would
# this file SHIP", and an ambiguous path is deliberately treated as "not
# SHIP" here rather than re-litigating the census's own refusal one door over.
bucket_for_path() {
    local hits
    hits=$(rules_for "$1")
    set -- $hits
    if [ "$#" -ne 1 ]; then
        printf 'AMBIGUOUS'
        return 0
    fi
    bucket_for_rule "$1"
}

# --- the archaeology-census patterns (docs/product's build history is not ---
# --- the product's) ---------------------------------------------------------
#
# THE PATTERNS ARE ASSEMBLED, NEVER SPELLED, wherever a literal would match
# itself. This file SHIPS (bucket R3 via rules_for's own `scripts/*` case), so
# a deny-listed name or a narrative phrase written out in full here IS the
# string the census refuses — the same hazard `rules_for`'s R8S arm and every
# drive's fixture paths are written around, and the same fix: name it in
# halves no pattern can join.
#
# `archaeology_patterns` echoes one TAB-separated `label<TAB>ere<TAB>scrub`
# row per pattern, in a fixed order, so both callers (the full-tree scan and
# the changed-files scan) read the identical six classes from the identical
# six expressions — the whole point of extracting this at all.
archaeology_patterns() {
    local _ru=rung _at=icus _ac=us-crm _jo=union _pd='\.dev' _bs=Bootstrap _ev='[-/](staging|prod)'
    # 1 · finding ids. The queue's row ids, which live in a ledger that ships
    #     as a skeleton — so every one of them resolves nowhere in the
    #     artifact. `scrub-noqa` strips a `noqa: <CODE>` directive first: a
    #     linter code shares the finding id's shape and is not one.
    printf 'finding-id\t\\bN[0-9]{2,3}\\b\tscrub-noqa\n'
    # 2 · rung and cycle tokens. `[A-Za-z0-9]` rather than `[A-Z0-9]` because
    #     the trailing lower-case forms are the same coordinate in the same
    #     plans (2026-08-31 finding: a digit-only suffix requirement reported
    #     zero over a tree carrying dozens of letter-suffixed tokens).
    printf 'rung-token\t\\bP[0-9]{1,2}-[A-Za-z0-9]+\\b\t\n'
    # 3 · the NARRATIVE forms of the method's vocabulary, and only those. A
    #     named verification pass is an instance of a run nobody outside this
    #     repository watched; the bare stage name is shipped vocabulary.
    printf 'narrative\tPROVE-[A-Za-z0-9]+|this %s\t\n' "$_ru"
    # 4 · the private-name deny-list: the sibling product, its repository
    #     slug, the owner's account handle, and the platform's own deployment
    #     domain.
    printf 'private-name\tAtt%s|attic%s|joe%s|pilecap%s\t\n' "$_at" "$_ac" "$_jo" "$_pd"
    # 5 · the template's FORMER name, TitleCase, matched CASE-SENSITIVELY —
    #     the discriminator between the identity that moved and the lowercase
    #     infrastructure namespace (compose project, `DJB_`/`djb_` prefixes,
    #     Zitadel logins) that the owner's ruling of 2026-08-26 kept.
    printf 'former-brand\tDjango%s\t\n' "$_bs"
    # 6 · deployment coordinates: the slug joined to an environment by `-`
    #     (IAM roles, S3 buckets, EC2 tags) or by `/` (the secrets-manager
    #     prefix). The slug ALONE is the product name and ships; the JOIN
    #     names somebody's real resources.
    printf 'deploy-coordinate\tpilecap%s\t\n' "$_ev"
}

# archaeology_class_report <label> <ere> <scrub> <hits-file>
#
# <hits-file> holds `grep -InE` output (`file:line:text` per line, one call
# per pattern). Prints one `archaeology-census: file:line  label  "matched"`
# line per genuine finding TO STDOUT AND NOTHING ELSE — a caller counts
# violations by counting the lines this prints, never by capturing this
# function's own output (a `$(...)` capture would swallow the very lines it
# is meant to let through). Internal to this file — both scan entry points
# below call it; nothing else needs to.
archaeology_class_report() {
    local label=$1 pat=$2 scrub=$3 hitsfile=$4
    local hit file line text matched
    while IFS= read -r hit; do
        [ -n "$hit" ] || continue
        hit=${hit#./}
        file=${hit%%:*}
        hit=${hit#*:}
        line=${hit%%:*}
        text=${hit#*:}
        if [ -n "$scrub" ]; then
            # ALLOW-LIST, with its reason: a linter rule id inside a `noqa:`
            # directive shares the finding id's shape and is not one.
            text=$(printf '%s' "$text" |
                sed -E 's/noqa:[[:space:]]*[A-Z]+[0-9]+([[:space:]]*,[[:space:]]*[A-Z]+[0-9]+)*//g')
        fi
        # ALLOW-LIST, with its reason: compose.yaml's MinIO pin, that one line,
        # names the owner's ghcr.io namespace — the owner named it on
        # 2026-10-26; the pin moves to the organization's namespace with the
        # organization repository, and this arm is removed with it.
        if [ "$label" = private-name ] && [ "$file" = compose.yaml ] &&
            [[ "$text" =~ ^[[:space:]]*image:[[:space:]]*ghcr\.io/joe"union"/minio:[^[:space:]]+$ ]]; then
            continue
        fi
        # READ WHOLE, THEN SLICE. This file is SOURCED by `scripts/check.sh`,
        # which runs under `set -o pipefail`: a `| head -1` here closes the pipe
        # on the first match and orphans grep on any line long enough to fill a
        # 64 KiB pipe buffer — a minified asset, a base64 blob — so the census
        # would die of the one file it most wanted to report.
        matched=$(printf '%s' "$text" | grep -oE "$pat" || true)
        matched=${matched%%$'\n'*}
        [ -n "$matched" ] || continue
        printf 'archaeology-census: %s:%s  %s  "%s"\n' "$file" "$line" "$label" "$matched"
    done <"$hitsfile"
}

# archaeology_scan_tree <target-dir>
#
# The FULL scan: every one of the six patterns, over every file under
# <target-dir> (excluding .git/), exactly as `publish.sh`'s release-time
# census always ran it. Prints one line per finding to stdout (the caller
# decides how loudly to say VIOLATION); returns 0 once every pattern has run
# cleanly, 2 if a `grep` call itself could not read the tree (could-not-look,
# never a silent zero).
archaeology_scan_tree() {
    local target=$1 hits label pat scrub rc
    hits=$(mktemp "${TMPDIR:-/tmp}/djb-arch-hits.XXXXXX") || return 2
    while IFS=$'\t' read -r label pat scrub; do
        set +e
        (cd "$target" && grep -rInE "$pat" --exclude-dir=.git .) >"$hits" 2>/dev/null
        rc=$?
        set -e
        if [ "$rc" -gt 1 ]; then
            gate_refuse "archaeology-census: the scan for '$label' could not read the artifact"
            echo "   (grep exited $rc). A tree nobody looked at is not a clean tree." >&2
            rm -f "$hits"
            return 2
        fi
        archaeology_class_report "$label" "$pat" "$scrub" "$hits"
    done < <(archaeology_patterns)
    rm -f "$hits"
    return 0
}

# archaeology_scan_files <path> [path ...]
#
# The NARROWED scan (the per-rung --loop leg): the identical six patterns, over an
# explicit file list rather than a directory walk — sub-second because the
# list is the active rung's own changed files, never the whole tree. Same
# output shape and same exit semantics as archaeology_scan_tree, so a reader
# comparing the two legs' output is comparing like with like.
#
# `-H`, ALWAYS. `grep` only PREFIXES the filename when it is given more than
# one, so a rung that changed exactly one bucket-SHIP file — the common
# case — would otherwise hand `archaeology_class_report` a bare `line:text`
# with no filename at all, which the parser reads as `file=<line number>`
# and `line=<the first word of the text>`: a wrong citation printed with
# total confidence. Found live, by this file's own drive, the first time it
# ran a single-file case.
archaeology_scan_files() {
    local hits label pat scrub rc
    [ "$#" -gt 0 ] || return 0
    hits=$(mktemp "${TMPDIR:-/tmp}/djb-arch-hits.XXXXXX") || return 2
    while IFS=$'\t' read -r label pat scrub; do
        set +e
        grep -HInE "$pat" -- "$@" >"$hits" 2>/dev/null
        rc=$?
        set -e
        if [ "$rc" -gt 1 ]; then
            gate_refuse "archaeology-census: the scan for '$label' could not read the changed files"
            echo "   (grep exited $rc). A tree nobody looked at is not a clean tree." >&2
            rm -f "$hits"
            return 2
        fi
        archaeology_class_report "$label" "$pat" "$scrub" "$hits"
    done < <(archaeology_patterns)
    rm -f "$hits"
    return 0
}

# archaeology_loop
#
# The `--loop` `archaeology` leg's whole body: derive the active
# rung's changed files (reusing `secrets_scan_changed_files`,
# scripts/secrets_scan.sh:59 — one derivation, not a second copy of it),
# narrow to the SHIP bucket, and run the six patterns against ONLY those.
#
# THE BUCKET CLASSIFIER IS NOT OPTIONAL (stated as the
# hazard it is): a rung that only changed docs/product/queue.md — a
# SKELETON file (bucket R7) whose worked example and every PM update row
# afterwards is FULL of finding ids and rung tokens by design — must not
# redden here. Narrowing to bucket SHIP is what tells "the platform's own
# vocabulary, in a ledger that never ships" apart from "the platform's own
# vocabulary, in a file that will".
#
# Exit: 0 clean (including "nothing to scan") · 1 a finding in the changed
# SHIP-bucket set · 2 could-not-look (the changed-file derivation failed, or
# a `grep` call itself could not run).
archaeology_loop() {
    local list f rc bad n out
    list=$(mktemp "${TMPDIR:-/tmp}/djb-arch-changed.XXXXXX") || return 2
    if ! secrets_scan_changed_files "$list"; then
        rm -f "$list"
        return 2
    fi
    echo "  basis: ${SECRETS_SCAN_BASIS}"

    local ship=()
    while IFS= read -r -d '' f; do
        [ -n "$f" ] || continue
        [ -f "$f" ] || continue
        case "$(bucket_for_path "$f")" in
        SHIP) ship+=("$f") ;;
        esac
    done <"$list"
    rm -f "$list"
    n=${#ship[@]}

    if [ "$n" = "0" ]; then
        echo "  NOTHING TO SCAN: the active rung changed no bucket-SHIP file. A SKELETON"
        echo "  ledger row citing a finding id or a rung token is expected vocabulary, not"
        echo "  archaeology — the bucket classifier (rules_for/bucket_for_rule,"
        echo "  scripts/archaeology_lib.sh) is what tells the two apart, and it is not"
        echo "  optional: this leg would otherwise redden on every PM ledger commit."
        return 0
    fi

    echo "  scanning $n changed bucket-SHIP file(s) for the six archaeology-census"
    echo "  patterns (finding-id, rung-token, narrative, private-name, former-brand,"
    echo "  deploy-coordinate) — the full artifact scan stays at push, in publish.sh."

    out=$(mktemp "${TMPDIR:-/tmp}/djb-arch-out.XXXXXX") || return 2
    archaeology_scan_files "${ship[@]}" >"$out"
    rc=$?
    if [ "$rc" = "2" ]; then
        rm -f "$out"
        return 2
    fi

    bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "  VIOLATION  $line"
        bad=$((bad + 1))
    done <"$out"
    rm -f "$out"

    if [ "$bad" = "0" ]; then
        echo "  ok — no finding id, rung token, narrative instance, private name, former"
        echo "  brand or deployment coordinate in the changed SHIP-bucket set"
        return 0
    fi
    return 1
}
