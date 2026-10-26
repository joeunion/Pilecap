#!/usr/bin/env bash
# Per-CHECKOUT database naming and helpers.
#
#   source scripts/db.sh          # exports DATABASE_NAME
#   db_name · db_create · db_drop · db_exists
#   db_template_refresh           # publish the migrated template
#
# Every checkout gets its own database on the one compose Postgres, so a tree's
# gate measures its own tree and nothing else.
#
# The name follows the CHECKOUT, not the branch. Two clones of `main` in
# two directories used to derive djb_main and share it — with the owner's live
# development database — and exporting DATABASE_NAME first was no escape,
# because this file set it unconditionally. Both halves are fixed here:
#
#   1. A DATABASE_NAME already in the environment WINS, and nothing is derived.
#      That is the escape: `DATABASE_NAME=djb_custom ./scripts/test.sh`, or an
#      export before sourcing, reaches every consumer through this one variable.
#      The one exception: a name this file derived for ANOTHER checkout (its
#      label says `derived`, its path hash is not this one's) is re-derived and
#      said in one `!!` line — test_db.py::test_two_verifier_clones_derive_two_names.
#   2. Otherwise the name is djb_<branch>_<hash>, where <hash> is the first 8
#      hex digits of the SHA-256 of the checkout's absolute top-level path
#      (git's, so it is the same however you cd into the tree). The branch keeps
#      the name readable at a glance; the path hash is what makes it this
#      checkout's and nobody else's.
#
# THE DECLARATION BELOW IS READ BY `scripts/gate_ledger.sh`. The `--loop`
# ledger's environment fingerprint hashes `.env` so that a verdict earned under
# one configuration cannot vouch for another. A key this file DERIVES from the
# checkout's own path would put every checkout's directory into that hash and no
# verdict would ever be reused anywhere — so the deriver declares what it
# derives, beside the derivation, in the file whoever changes it already has
# open. A list in the ledger would be right on the day it was written.
# `loop_env_derived_keys` finds zero declarations only when this convention is
# gone, and answers that by hashing the whole file — a miss, never a hit on an
# exclusion nobody could verify.
#
# >>> derived-env-keys >>>
# DATABASE_NAME — db_name_for below: djb_<the branch, lower-cased, every other
#   character `_`, at most 38; detached or empty is main>_<the first 8 hex of the
#   SHA-256 of git's top level, or $PWD outside a repository>, pinned by
#   quality/tests/test_db.py::test_db_name_for_is_db_name_of_that_checkout and
#   written into .env by scripts/rung_start.sh and scripts/verify_start.sh.
# <<< derived-env-keys <<<
#
# Identifier arithmetic — Postgres allows 63 bytes, and it TRUNCATES rather
# than refusing, so two names that differ only past byte 63 become one database.
# The budget now has a fourth term: djb_(4) + branch(<=38) + _(1) + hash(8) =
# 51, Django's `test_` prefix takes that to 56, and pytest-xdist's per-worker
# suffix (`_gw0`..`_gw999`, up to 6) takes it to 62 — one byte spare.
#
# The branch cap is 38 and not 40 because of that last term (ADR gate-1 landed
# the workers): at 40 the test name reached 58 and `_gw100` truncated to
# `_gw10`, so worker 100 and worker 10 would share one database and produce
# failures nobody could reproduce. Two bytes bought the whole `_gwN` range.
#
# Two consequences, both accepted and stated: a checkout MOVED on disk derives
# a new name and leaves its old database behind, and names derived before this
# scheme existed (djb_main, djb_worktree_agent_*) are not the names derived
# now. Nothing here drops or renames a database to catch up — another
# checkout's data is not this script's to touch. A checkout that wants to keep
# an old-scheme database keeps it by pre-setting DATABASE_NAME, which is rule 1
# above and now works.
#
# This file is meant to be sourced. It sets no shell options of its own so it
# cannot change the caller's behaviour.
#
# --- THE SOURCED-LIBRARY CONTRACT -------------------------------------------
#
# The shebang on line 1 is INERT. Nothing executes this file; every consumer
# sources it, so the interpreter is always the CALLER'S shell and never the one
# named above. On this machine that caller is usually bash, and on a laptop
# whose default shell is zsh — macOS since Catalina — a `. scripts/db.sh` at an
# interactive prompt is zsh. So the contract this file signs is: it is POSIX-ish
# shell that must behave IDENTICALLY under bash and under zsh, and the belt for
# a shell that cannot run it is the caller's, not this file's. A `BASH_VERSION`
# refusal HERE would refuse the exact case this paragraph exists to support.
#
# ONE RULE, AND IT HAS ALREADY COST A REAL FALSE GREEN. zsh has TIED and SPECIAL
# parameters, and `local` does not untie them: `local path=fallback` inside a
# function does not make a private string, it sets the caller's PATH to
# `fallback` for the length of that function. `db_create_the_checkouts_own` did
# exactly that. Under zsh, with docker on PATH and the server up, it printed
#
#     db_psql:1: command not found: docker
#     created database djb_...            <- and no database was created
#
# and returned 0. Every tool the function needed — docker, awk, date — vanished
# mid-function, and the one line the caller reads said the work was done.
#
# THE CLOSED AUDIT, run over this whole file and printed here so a reader does
# not have to re-derive it. Never use any of these as a variable name, `local`
# or not:
#
#   path      tied to PATH (array<->scalar). The one that bit us.
#   status    zsh's `$?` under another name; assigning it rewrites exit status.
#   options   the shell's own option table; assigning it can change behaviour.
#   fignore   filename-completion ignore list; assigning it changes globbing.
#
# As of this file today the audit finds ONE occurrence and it is the fix below:
# `path` in `db_create_the_checkouts_own` became `creation_path`. `status`,
# `options` and `fignore` appear nowhere in this file as variables, and the two
# `path` matches in `db_migration_listing` are `find -path` OPERANDS, not shell
# parameters — no change was needed for those and none was made. The wider
# zsh-tied set (`cdpath`, `fpath`, `manpath`, `argv`, `psvar`, `signals`,
# `module_path`, `mailpath`, `watch`, `prompt`, `histchars`) was grepped beside
# the four and appears nowhere in this file at all.
#
# `quality/tests/test_db.py` is the tooth: it sources this file under a REAL
# zsh and drives `db_create`, asserting the created database EXISTS. It skips
# with a reason when there is no zsh, and never passes vacuously.

# The digest tool, this file's one ladder: `db_path_hash`, the per-file pass and the final
# string pass all ask it. `db_path_hash`'s `cksum` last resort is NOT
# acceptable here — 32 bits over a machine-global schema key is a collision
# waiting to hand somebody the wrong migration set — so no tool is a REFUSAL
# and the refusal lands on the loud fallback path, which is correct and slow.
db_digest_tool() {
    if command -v shasum >/dev/null 2>&1; then
        printf 'shasum'
    elif command -v sha256sum >/dev/null 2>&1; then
        printf 'sha256sum'
    else
        return 1
    fi
}

# First N hex digits of the SHA-256 of $1 (N defaults to 8), with fallbacks down
# to a POSIX one, because this must not need a tool a fresh laptop might not
# have. The length argument arrived with the template key, which wants 16
# — a machine-global name where a collision would hand one checkout another
# migration set's schema, which 8 hex digits is too short to promise.
db_path_hash() {
    local input="$1" want="${2:-8}" digest=""
    case "$(db_digest_tool)" in
    shasum) digest="$(printf '%s' "$input" | shasum -a 256 | awk '{print $1}')" ;;
    sha256sum) digest="$(printf '%s' "$input" | sha256sum | awk '{print $1}')" ;;
    esac
    if [ -n "$digest" ]; then
        :
    elif command -v openssl >/dev/null 2>&1; then
        # `SHA2-256(stdin)= <hex>` — the digest is the last field.
        digest="$(printf '%s' "$input" | openssl dgst -sha256 | awk '{print $NF}')"
    else
        # cksum is in POSIX and separates two paths, which is the whole job.
        digest="$(printf '%08x' "$(printf '%s' "$input" | cksum | awk '{print $1}')")"
    fi
    printf "%.${want}s" "$digest"
}

# db_name_for <branch> <path> — the database and queue name of a checkout of <branch> whose top level is <path>.
# A detached or empty branch is `main`; 38 characters, not 40 — `test_` plus xdist's `_gw999`.
db_name_for() {
    local branch="${1:-}" root="${2:-}" sanitised
    if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
        branch="main"
    fi
    sanitised="$(printf '%s' "$branch" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '_')"
    sanitised="${sanitised:0:38}"
    [ -n "$sanitised" ] || sanitised="main"
    printf 'djb_%s_%s' "$sanitised" "$(db_path_hash "$root")"
}

# road: checkout_name — this checkout's database and queue name, derived once · example: quality/tests/test_db.py::test_the_key_is_the_same_wherever_the_checkout_lives
# The checkout's own top level (a linked worktree reports itself); outside a repository, the working directory.
db_name() {
    local root
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    [ -n "$root" ] || root="$PWD"
    db_name_for "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)" "$root"
}

# db_name_hash <name> — the 8-hex path hash a derived name ends in; nothing for a name typed by hand.
db_name_hash() {
    case "$1" in
    djb_*_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) printf '%s' "${1##*_}" ;;
    esac
}

# db_is_foreign <name> — true when <name> was derived for another checkout (rule 6: one checkout, one database).
db_is_foreign() {
    local digest
    digest="$(db_name_hash "$1")"
    [ -n "$digest" ] && [ "$digest" != "$(db_path_hash "$(db_checkout_root)")" ]
}

# db_say_foreign <name> — the one line naming another checkout's name and this checkout's own.
db_say_foreign() {
    printf '!! DATABASE_NAME %s was derived for another checkout (%s); this checkout derives %s\n' \
        "$1" "$(db_name_hash "$1")" "$(db_name)" >&2
    DB_FOREIGN_SAID="$1"
    return 0
}

# Rule 1: a name already in the environment wins. `:-` and not `-`, so an empty
# DATABASE_NAME derives rather than exporting nothing. Sourcing twice is
# therefore stable — the second source honours the first one's export — and so
# is a script that sources this file and then calls another one that does too.
#
# THIS LINE IS THE PRECEDENCE, AND IT IS THE ONLY COPY OF IT. Every consumer
# reads the RESULT — `$DATABASE_NAME` — and none of them re-decides: `db_exists`,
# `db_create`, `db_drop` default their argument to it, `backup.sh::db_present`
# reads it, `test.sh` and the gate inherit it. A second place that asked "is
# there an override?" would be a second precedence, and two precedences is the
# split brain this whole file is written against.
#
# WHAT THE LINE COLLAPSES, AND WHY THAT COST A LEG ITS POINT. `${X:-default}`
# yields a name and throws away WHERE THE NAME CAME FROM, and until this comment
# nothing needed the difference. The db-pin leg does: it reports on the database
# a run will USE, and "djb_x exists" is a different sentence depending on whether
# djb_x was derived from this checkout or handed in by an operator who meant
# something else. Measured: with `DATABASE_NAME=djb_vg1r_does_not_exist`
# exported, the leg printed `database djb_rung_… exists` and exited 0 — vouching,
# under the override, for a database the suite would not open.
#
# So the provenance is recorded HERE, beside the decision, and never re-derived.
# It is EXPORTED with the name so the two travel together, and it is set only
# when it is not already set: a child that inherits both keeps the parent's
# answer, so a script that derived and then ran another script does not have its
# derived name re-labelled "exported" by the second source.
#
# AND THE LABEL IS A HINT, NOT A PROOF. It is sticky, it crosses process
# boundaries, and both of those are on purpose — which together mean it can
# describe a name that is no longer in the variable:
#
#   * SAME PROCESS. A shell sources this file (label: `derived`) and then types
#     `export DATABASE_NAME=something_else`. Nothing re-sources, so the label
#     stands over a value it was never true of.
#   * ACROSS A PROCESS. A shell sources this file — which is exactly what
#     `setup.sh`'s closing "Next:" block tells an operator to do — and then runs
#     `DATABASE_NAME=other ./some_script.sh`. The child inherits the LABEL from
#     the parent and the NAME from the command line, and when it sources this
#     file the guard above sees a label already set and leaves `derived` in
#     place. Measured: parent `SOURCE=derived`, child `DATABASE_NAME=djb_absent
#     SOURCE=derived`, and the leg vouched for the derived name at exit 0.
#
# An earlier fix recorded the resolved VALUE here beside the label and compared
# the two. It closed the first case and not the second, because this block runs
# in the child as well and re-recorded the value the child was handed — so the
# pair agreed and the label was believed. The lesson is that NOTHING RECORDED
# HERE CAN AUTHENTICATE ITSELF ACROSS A SOURCE: whatever this block writes, the
# next source writes again, from data the caller controls.
#
# So the check does not live here at all. A consumer that must know whether the
# label is still true compares `$DATABASE_NAME` against the name it would
# DERIVE — `db_name`, computed from the checkout, which no environment can
# forge — and `db_pin_effective_name` below is that consumer. A label is
# something to print; the derivation is something to check against.
# The line itself is `db_resolve_name`, below `db_pin_decide`, whose verdict it reads.

# --- Rule 1 stops being SILENT about itself ---------------------------
#
# THE SPLIT-BRAIN. `.env` is read by django-environ at settings import, so a
# bare `manage.py` resolves whatever `.env` pins. This file is sourced by the
# scripts, and it derives. When those two disagree, one checkout has TWO
# databases and nothing says so: once, the main checkout's `.env`
# pinned the old-scheme flat `djb_main` (the owner's live development database)
# while every script exported `djb_main_700aaf41`, which had never been
# migrated — so `serve.sh` 500ed on any table read while `manage.py` worked
# fine, and a PM debugging it migrated and minted tokens into the OWNER'S
# database. Every part of that was legal. None of it was visible.
#
# SO THE RULE IS UNCHANGED AND THE SILENCE IS NOT. A pin still wins — the
# owner may pin deliberately, and refusing here would fight rule 1's recorded
# semantics (and break every `DATABASE_NAME=x ./scripts/test.sh` in the
# repository). What changes is that a disagreement now says so, once, on every
# source. A pin stays legal; a STALE pin stops being invisible.
#
# AND THAT NOTE IS ONLY THE SECONDARY HALF. Saying so was not enough:
# a later census found the main checkout's pin still stale a day after this
# note shipped, and 63 stale worktree pins beside it. The primary enforcement
# is now `db_pin_leg` below — the gate's `db-pin` leg, in `--fast`, which a
# commit has to answer. The note stays as a heads-up for a script run outside
# the gate and points at the leg rather than restating its fixes.
#
# ON STDERR, and never on stdout: this file is sourced by scripts whose stdout
# is data — `gen_client.sh` writes a schema, `backup.sh` writes a dump through
# a redirect, `db_sweep.sh`'s census is read by eye and by grep. A notice on
# stdout would corrupt the first and be mistaken for a finding in the last.
#
# SILENT WHEN THEY AGREE, which is the normal case and every gate run: this
# prints only on an actual disagreement, so it can never become noise a reader
# learns to skip.
#
# WHAT IT DOES NOT SEE, declared: it compares against `.env` in the CHECKOUT
# ROOT only — a `DJANGO_SETTINGS_MODULE` pointing somewhere with its own
# environment file, or a value exported by a shell profile, is outside it. And
# it reports a DISAGREEMENT, never a wrongness: which of the two names is the
# right one is a judgement about intent that no script can make.
db_env_file_pin() {
    # The last `DATABASE_NAME=` line in the checkout's .env, unquoted — the
    # same "last wins" reading `backup.sh::env_value` uses, and the same one
    # django-environ ends up with. Prints nothing when there is no pin.
    local root line
    root="$(db_checkout_root)"
    [ -f "${root}/.env" ] || return 0
    line="$(grep -E '^DATABASE_NAME=' "${root}/.env" 2>/dev/null | tail -1 || true)"
    [ -n "$line" ] || return 0
    line="${line#DATABASE_NAME=}"
    # NOTHING IS STRIPPED AFTER THE `=` ANY MORE, AND THAT IS THE FIX.
    #
    # This used to do `line="${line%%#*}"`, so `DATABASE_NAME=djb_x  # pinned`
    # compared as `djb_x`. That made this function agree with `sh`'s reading of
    # the line and disagree with the reading that actually matters: `.env` is
    # read by django-environ, and `environ.Env.read_env` does NOT strip a
    # trailing comment. Measured on this tree:
    #
    #   line               DATABASE_NAME=djb_probe_value  # pinned
    #   environ.read_env   'djb_probe_value  # pinned'
    #   docker --env-file  'djb_probe_value  # pinned'
    #   shell `. .env`     'djb_probe_value'
    #
    # Two of the three readers keep the comment. So the strip did not remove
    # noise, it removed EVIDENCE: a pin whose value agreed with the derivation
    # once the comment was cut passed this leg silently, while a bare
    # `manage.py` resolved a database name with `# pinned` inside it. That is
    # the split brain this whole section exists to refuse, wearing the marker
    # that was supposed to prove somebody meant it.
    #
    # The value is therefore reported RAW, exactly as environ will read it, and
    # `db_pin_leg` refuses an inline comment outright (the marker's grammar is
    # now its own comment line ABOVE a bare value — see `db_pin_marked`).
    line="${line%"${line##*[![:space:]]}"}"
    # Strip a surrounding quote pair, the way django-environ does, so a
    # hand-written `DATABASE_NAME="djb_x"` compares as `djb_x`. The escapes are
    # load-bearing: `'*'` as a case pattern is the literal three characters
    # quote-star-quote, so the branches below matched nothing but a value that
    # WAS a single `*` until this was written properly (found while building
    # the db-pin leg, which would have read a quoted pin as a disagreement).
    case "$line" in
    \'*\') line="${line#\'}"; line="${line%\'}" ;;
    \"*\") line="${line#\"}"; line="${line%\"}" ;;
    esac
    printf '%s' "$line"
}

# The checkout root, or $PWD outside a repository. One definition, because the
# pin, the marker and the derivation must all be read out of the SAME tree.
db_checkout_root() {
    git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD"
}

# --- THE MARKER'S GRAMMAR, AND WHY IT MOVED ---------------------------------
#
# THE MARKER LIVES ON ITS OWN COMMENT LINE, DIRECTLY ABOVE A BARE VALUE:
#
#     # pinned
#     DATABASE_NAME=djb_x
#
# and NOT `DATABASE_NAME=djb_x  # pinned`, which is what this file prescribed
# until now. The inline form is not a style preference that lost; it is
# CORRUPTING. `.env` has three readers here and they do not agree about a
# trailing comment (measured, see `db_env_file_pin`): a shell `. .env` strips
# it, and `environ.Env.read_env` — the reader every bare `manage.py` goes
# through — and `docker --env-file` both keep it IN THE VALUE. So the marker
# that says "a human meant this name" was, at the same time, changing the name
# for two readers out of three. A checkout following the old instruction ended
# up resolving a database called `djb_x  # pinned`.
#
# The own-line form has no such split: every reader treats a whole-line comment
# as a comment, and all three then yield the identical clean value. The comment
# line may carry a reason after the word — `# pinned — the owner's live db` —
# and that is encouraged; what it may not do is share a line with the value.
#
# THE ANCHOR IS ADJACENCY, and it is as strict as the old grammar's was. The
# old rule was "on the DATABASE_NAME line", so that a file merely CONTAINING
# the word could not silence the leg. The new rule is "on the line immediately
# above the DATABASE_NAME line the pin is read from" — the LAST one, matching
# django-environ's last-wins reading and `db_env_file_pin`'s. A `# pinned`
# anywhere else in the file is still not this line's marker.
#
# THE GRAMMAR IS ONE CONSTANT, and it has two readers: `db_pin_marked` below,
# and `setup.sh`'s env-sync render, which rebuilds `.env` from `.env.example`
# and must carry the marker line through the rebuild or it erases the pin it
# was told to keep. Both hand it to awk through `ENVIRON`, so there is no second
# spelling of the regex anywhere to be left behind when the grammar moves.
DB_PIN_MARKER_ERE='^[[:space:]]*#[[:space:]]*pinned([[:space:]].*)?$'
db_pin_marked() {
    local root
    root="$(db_checkout_root)"
    [ -f "${root}/.env" ] || return 1
    # `marked` is re-decided at every DATABASE_NAME line, so the LAST one wins,
    # which is the line `db_env_file_pin` reports and the one environ resolves.
    DB_PIN_MARKER_ERE="$DB_PIN_MARKER_ERE" awk '
        /^DATABASE_NAME=/ { marked = previous_line_is_marker }
        { previous_line_is_marker = ($0 ~ ENVIRON["DB_PIN_MARKER_ERE"]) }
        END { exit(marked ? 0 : 1) }
    ' "${root}/.env" 2>/dev/null
}

# Does the .env's operative DATABASE_NAME line carry an INLINE comment? That is
# the corrupting form above, and `db_pin_leg` refuses it outright — including
# when the value before the `#` happens to equal the derivation, because the
# value AFTER environ reads it does not.
db_pin_line_has_inline_comment() {
    local root operative
    root="$(db_checkout_root)"
    [ -f "${root}/.env" ] || return 1
    operative="$(grep -E '^DATABASE_NAME=' "${root}/.env" 2>/dev/null | tail -1 || true)"
    case "$operative" in
    *"#"*) return 0 ;;
    *) return 1 ;;
    esac
}

# --- THE DECISION TABLE, ONCE ------------------------------------------------
#
# db_pin_decide — what does this checkout's `.env` pin SAY, against the
# derivation? One function, and every reader of the pin that has to act on the
# answer calls it: `db_pin_leg` (the gate's refusal), `setup.sh` (the writer
# that reconciles) and `db_announce_pin_disagreement` (the source-time note).
#
# WHY IT IS ONE FUNCTION. The leg and setup.sh used to carry the table twice,
# and the two copies disagreed on one cell: `.env` carrying an UNMARKED pin
# that differs from the derivation, with the same name exported in the shell
# (a shell that sourced db.sh before the checkout moved). setup.sh wrote the
# exported name back over the pin and migrated it; the leg read the same
# `.env`, found a disagreement with no marker, and refused — naming setup.sh as
# the remedy. The remedy was the instrument that disagreed with it, and a
# checkout went round that loop until a human read both. One table has no
# second cell to disagree with (principle 9: one owner, one resolver).
#
# IT DECIDES AND PRINTS NOTHING. Each caller owns its voice — the leg refuses,
# setup.sh reconciles, the note notes — and none of them re-derives the
# verdict. It sets four globals:
#
#   DB_PIN_VERDICT   no-env      no .env in the checkout
#                    unreadable  an .env that cannot be read
#                    no-line     an .env with no DATABASE_NAME line
#                    inline      the operative line carries an inline comment
#                                (the corrupting form; THE MARKER'S GRAMMAR)
#                    agree       the pin equals the derivation
#                    marked      the pin differs and the marker sits above it
#                    disagree    the pin differs and nothing marks it
#   DB_PIN_VALUE     the pin, raw as environ reads it (empty for the first three)
#   DB_PIN_DERIVED   `db_name` for this checkout, computed now
#   DB_PIN_MARKED    1 when the marker sits directly above the operative line,
#                    WHATEVER the verdict. setup.sh's "leave it alone" reads
#                    this rather than the verdict: an inline line under a marker
#                    is refused by the leg, but it is still a line a human
#                    marked, and what setup.sh may OVERWRITE is a question about
#                    the marker, not about the comparison.
#
# THE ORDER IS THE LEG'S ORDER and it is load-bearing: an inline comment is
# judged before agreement (the value environ reads carries the comment, so an
# "agreeing" inline line is the worst case, not the safe one), and agreement
# before the marker (a marked pin that agrees has nothing to excuse).
db_pin_decide() {
    local root
    DB_PIN_VERDICT=""
    DB_PIN_VALUE=""
    DB_PIN_MARKED=""
    DB_PIN_DERIVED="$(db_name)"
    root="$(db_checkout_root)"
    if [ ! -f "${root}/.env" ]; then
        DB_PIN_VERDICT="no-env"
        return 0
    fi
    if [ ! -r "${root}/.env" ]; then
        DB_PIN_VERDICT="unreadable"
        return 0
    fi
    DB_PIN_VALUE="$(db_env_file_pin)"
    if [ -z "$DB_PIN_VALUE" ]; then
        DB_PIN_VERDICT="no-line"
        return 0
    fi
    if db_pin_marked; then
        DB_PIN_MARKED=1
    fi
    if db_pin_line_has_inline_comment; then
        DB_PIN_VERDICT="inline"
    elif [ "$DB_PIN_VALUE" = "$DB_PIN_DERIVED" ]; then
        DB_PIN_VERDICT="agree"
    elif [ -n "$DB_PIN_MARKED" ]; then
        DB_PIN_VERDICT="marked"
    else
        DB_PIN_VERDICT="disagree"
    fi
    return 0
}

# db_resolve_name — rule 1's line: an export wins; else a `# pinned` .env line; else the derivation.
# The pin is read through `db_pin_decide`, the verdict `db_pin_leg` reads, so every script that
# sources this file opens the database the gate vouched for (one reader of the pin, principle 9).
db_resolve_name() {
    if [ -z "${DATABASE_NAME_SOURCE:-}" ]; then
        if [ -n "${DATABASE_NAME:-}" ]; then
            DATABASE_NAME_SOURCE="DATABASE_NAME exported"
        else
            DATABASE_NAME_SOURCE="derived"
        fi
    fi
    DB_FOREIGN_SAID=""
    if [ -n "${DATABASE_NAME:-}" ] && db_is_foreign "$DATABASE_NAME"; then
        if [ -z "${DB_PIN_NOTE_OFF:-}" ]; then
            db_say_foreign "$DATABASE_NAME"
        fi
        # A label this file wrote is not an operator's choice: the name is re-derived here.
        if [ "$DATABASE_NAME_SOURCE" != "DATABASE_NAME exported" ]; then
            DATABASE_NAME=""
        fi
    fi
    if [ "$DATABASE_NAME_SOURCE" != "DATABASE_NAME exported" ] || [ -z "${DATABASE_NAME:-}" ]; then
        DATABASE_NAME="${DATABASE_NAME:-}"
        db_pin_decide
        case "${DATABASE_NAME}" in
        "" | "$DB_PIN_DERIVED")
            if [ "$DB_PIN_VERDICT" = "marked" ]; then
                DATABASE_NAME="$DB_PIN_VALUE"
                DATABASE_NAME_SOURCE=".env pin"
            else
                DATABASE_NAME="$DB_PIN_DERIVED"
                DATABASE_NAME_SOURCE="derived"
            fi
            ;;
        esac
    fi
    export DATABASE_NAME DATABASE_NAME_SOURCE
}
db_resolve_name

# --- THE REFUSAL SEAM -------------------------------------------------------
#
# `scripts/gate_refuse.sh`, sourced from THIS FILE'S OWN DIRECTORY and guarded
# against a second source, exactly as `scripts/archaeology_lib.sh` does it —
# one seam, not a second copy of it (principle 13). `db_pin_leg`'s refusals go
# through `gate_refuse` so the gate's `db-pin` banner can print `cause:` with
# the sentence the leg actually said, instead of `(the callee set none)`.
#
# `${BASH_SOURCE[0]:-$0}` AND NOT `${BASH_SOURCE[0]}`: this file is sourced by
# zsh as well as bash (THE SOURCED-LIBRARY CONTRACT above), zsh sets no
# BASH_SOURCE, and zsh's `$0` inside a sourced file IS this file. Measured under
# bash, zsh and dash: all three resolve to this file's path.
#
# THE SOURCE IS BEST-EFFORT, AND THE LEG IS NOT. A copy of db.sh living
# somewhere else — `test_db_zsh.sh`'s planted revert is the real case — has no
# seam beside it, and a hard `.` would kill the caller's shell. So it is
# guarded here and ANSWERED in `db_pin_leg`, which refuses with exit 2 when the
# seam is missing rather than printing a refusal nothing can attribute.
# shellcheck source=scripts/gate_refuse.sh
if [ -z "${GATE_REFUSE_SOURCED:-}" ]; then
    __db_self="${BASH_SOURCE[0]:-$0}"
    case "$__db_self" in
    */*) __db_seam="${__db_self%/*}/gate_refuse.sh" ;;
    *) __db_seam="scripts/gate_refuse.sh" ;;
    esac
    if [ -r "$__db_seam" ]; then
        . "$__db_seam"
    fi
    unset __db_self __db_seam
fi

# --- THE LEG ----------------------------------------------
#
# THE NOTE BELOW WAS SILENCE WITH EXTRA STEPS. `db_announce_pin_disagreement`
# has printed this disagreement on stderr on every single script run for a
# long stretch, and a census found the MAIN CHECKOUT'S pin still stale a
# full day later — with 63 stale worktree pins beside it. A note nobody has to
# answer is a note nobody answers; this class had already written to the
# owner's real database once before the note existed, and the note did not stop
# the second checkout from drifting.
#
# So the disagreement gets an EXIT STATUS. This function is the body of the
# `db-pin` leg in `scripts/check.sh` — a `--fast` leg, which means pre-commit
# runs it, and `--loop` and the full gate inherit it. A stale pin now stops a
# commit instead of scrolling past one.
#
# THE PIN STAYS LEGAL. Rule 1 above is untouched: a name in the environment
# still wins, and a `# pinned` .env line still keeps its name. What the marker
# buys now is SILENCE — the leg passes without a word, because a checkout that
# said it meant it has answered the question. A pin with no marker has not.
#
#   exit 0  no .env · no DATABASE_NAME line · the pin agrees · `# pinned`
#           on its own line above the value
#   exit 1  a pin disagreeing with the derivation, unmarked
#   exit 1  an INLINE comment on the DATABASE_NAME line, marked or not,
#           agreeing or not — the comment is inside the name for two of the
#           three readers, so there is nothing here a marker could excuse
#   exit 2  could not look — an .env in the tree that cannot be read
#   exit 2  the name the pin resolves to HAS NO DATABASE, under a mode that
#           binds existence (below)
#   exit 2  the compose Postgres is unreachable under a mode that binds
#           existence — could not look, never a pass
#   exit 2  no mode, or a mode this function does not know
#
# --- THE SECOND QUESTION: DOES THAT DATABASE EXIST? -------------------------
#
# COMPARING THE PIN WAS NEVER THE WHOLE JOB. A bank once ran ten green minutes
# — every leg, both pytest passes — and then `test_backup_restore.sh` refused
# because the primary checkout's database was not there at all. The pin had
# agreed with the derivation the whole time: this leg was asked whether the two
# names MATCH and answered that honestly, and nothing between it and the
# selftest leg ever asked whether the name it blessed opens anything. Ten
# minutes to reach a fact that costs one `SELECT 1 FROM pg_database`.
#
# SO THE LEG TAKES A MODE, AND THE MODE IS NOT DECORATION. `db_exists` runs
# `docker compose exec -T db psql` — it needs the stack up. `--fast` is defined
# by `docs/product/build-contract.md` § Interfaces as needing NO database ("No
# services needed beyond what mypy/django needs to import settings"), and
# pre-commit runs `--fast` on every laptop, stack up or down — yet `--fast`'s
# migrations leg opens the database (makemigrations' consistency check), so an
# absent one used to surface as a warning a minute in. So `fast` asks
# only where the answer is this checkout's own and costs one query: when the pin
# and the derivation agree (no pin counts), and only of a server that answers.
#
#   db_pin_leg fast    asked only when the pin and the derivation agree; absent → said, exit 0,
#                      naming ./scripts/setup.sh; a server that does not answer is said, not red
#   db_pin_leg loop    asked; absent → exit 2 naming ./scripts/setup.sh
#   db_pin_leg full    asked; the same refusal
#   every mode         a name another checkout derived (its path hash is not ours) → exit 1
#
# THE MODE IS PRINTED ON EVERY RUN, whatever the verdict. A leg with two
# behaviours and no line saying which one it is in is a leg whose green means
# one of two different things and does not say which (a recorded miss). The
# mode line is the FIRST thing this function prints, before the pin is even
# read, so it is there on the refusing paths too.
#
# AND AN ABSENCE IS NEVER INFERRED FROM A SILENCE. `db_exists` answers "no" both
# when the row is missing and when nothing answered the query at all, so a
# negative is CLASSIFIED before it is reported: `db_reachable` asks the server
# one more question, and a server that cannot be reached is a COULD NOT LOOK
# naming docker (exit 2) rather than a refusal blaming a database nobody managed
# to ask about. The pin comparison above stays readable and stays judged; what
# is unreadable is reported as unreadable and as nothing else.
#
# WHICH NAME IS ASKED ABOUT: the one the RUN WILL OPEN, resolved by
# `db_pin_effective_name` below, and the leg PRINTS which of the three sources it
# took. An exported `DATABASE_NAME` wins — rule 1's escape, the same value every
# consumer in this file already defaults to; otherwise it is what the pin
# comparison concluded, which is the derivation, or the pin itself where a
# `# pinned` marker keeps it. The three labels are `derived`, `.env pin` and
# `DATABASE_NAME exported`, and a verdict that did not name its source could not
# be told from one that had looked at the wrong database.
#
# THE TWO HALVES ASK DIFFERENT QUESTIONS, AND THAT IS DELIBERATE. The pin
# COMPARISON is `.env` against the derivation and is untouched by an export
# (below); the EXISTENCE check is about the name the run resolves. A checkout
# where those two disagree is a checkout where the comparison has something to
# say and the existence check has something else to say, and both get said.
#
# WHAT IT DOES NOT SEE, declared here because a leg is read as broader than a
# note: the COMPARISON reads `.env` in the CHECKOUT ROOT only. A
# `DJANGO_SETTINGS_MODULE` pointing at somewhere with its own environment file is
# outside it, and overrides .env for a bare `manage.py` — so a green comparison
# means "the file agrees", never "the process will". (A `DATABASE_NAME` exported
# by a shell profile used to be on this list. It is off it: the comparison still
# does not see it, and the existence check now does.)
# It also does not see whether the database it found is MIGRATED, or whether it
# is the one this tree's migrations belong to: a name that OPENS is the whole of
# the claim, and the incident above is about a name that opened nothing at all.
db_pin_leg() {
    local mode="${1:-}" root pin derived cleaned foreign
    # THE REFUSAL SEAM, CHECKED BEFORE ANYTHING ELSE. Every refusal below goes
    # through `gate_refuse` so the gate's banner can print `cause:` with the
    # sentence this function actually said. A copy of db.sh moved away from its
    # own directory cannot load the seam, and then the banner would say nobody
    # recorded a cause — which is broken enforcement, so it is a could-not-look
    # rather than a quiet downgrade to a bare `echo`.
    if ! command -v gate_refuse >/dev/null 2>&1; then
        echo "!! db-pin: the refusal seam (scripts/gate_refuse.sh) is not loaded." >&2
        echo "   scripts/db.sh sources it from its own directory; a copy of db.sh moved" >&2
        echo "   somewhere else cannot find it. Nothing was compared." >&2
        return 2
    fi
    case "$mode" in
    fast | loop | full) ;;
    "")
        gate_refuse "db-pin: db_pin_leg was called with no mode — it takes fast, loop or full."
        echo "   The leg BINDS this checkout's database existence under loop and full and" >&2
        echo "   does not ask under fast (--fast needs no database — build-contract.md" >&2
        echo "   § Interfaces). A leg that does not know which it is in would either red" >&2
        echo "   every laptop pre-commit with the stack down, or vouch for a database" >&2
        echo "   nobody looked at. Neither is a judgment this function may make on its" >&2
        echo "   caller's behalf, so a missing mode is could-not-look and not a default." >&2
        return 2
        ;;
    *)
        gate_refuse "db-pin: unknown mode '${mode}' — db_pin_leg takes fast, loop or full."
        echo "   A mistyped mode falling through to a silently different run is the same" >&2
        echo "   defect as a mistyped gate flag, and it gets the same answer: exit 2." >&2
        return 2
        ;;
    esac
    # THE MODE LINE. Printed before the pin is even read, so that it is on every
    # path out of this function — the two refusals above excepted, where the
    # mode is the thing that could not be read.
    if [ "$mode" = "fast" ]; then
        echo "  db-pin mode: fast — existence asked of the derived name only, a silent server said and not red"
    else
        echo "  db-pin mode: ${mode} — this checkout's database must exist"
    fi
    root="$(db_checkout_root)"
    # THE VERDICT IS `db_pin_decide`'S. This function maps it to a voice and
    # an exit status and decides nothing itself — setup.sh reads the same
    # verdict, so the refusal below and the reconciliation there cannot come to
    # disagree about which cell a checkout is in.
    db_pin_decide
    pin="$DB_PIN_VALUE"
    derived="$DB_PIN_DERIVED"
    foreign=""
    if [ -n "${DATABASE_NAME:-}" ] && db_is_foreign "$DATABASE_NAME"; then
        foreign="$DATABASE_NAME"
    elif [ -n "$pin" ] && db_is_foreign "$pin"; then
        foreign="$pin"
    fi
    if [ -n "$foreign" ]; then
        echo "RED: DATABASE_NAME ${foreign} was derived for another checkout ($(db_name_hash "$foreign")); this checkout derives ${derived}" >&2
        echo "   One checkout, one database: every step here would open that checkout's data." >&2
        if [ "$foreign" != "$pin" ]; then
            echo "     unset DATABASE_NAME DATABASE_NAME_SOURCE   # the shell carried it from there" >&2
        else
            echo "     ./scripts/setup.sh   # rewrites .env's line to ${derived} (a \`# pinned\` line above it goes first)" >&2
        fi
        return 1
    fi
    if [ "$DB_PIN_VERDICT" = "no-env" ]; then
        # No file, no second opinion: the derivation is the only truth here.
        echo "  no .env in this checkout — the derivation is the only name (${derived})"
        db_pin_existence "$mode" "$derived" derived
        return $?
    fi
    if [ "$DB_PIN_VERDICT" = "unreadable" ]; then
        gate_refuse "${root}/.env exists and cannot be read — the pin could not be compared."
        return 2
    fi
    if [ "$DB_PIN_VERDICT" = "no-line" ]; then
        echo "  .env pins no DATABASE_NAME — the derivation is the only name (${derived})"
        db_pin_existence "$mode" "$derived" derived
        return $?
    fi
    # THE CORRUPTED LINE IS REFUSED BEFORE ANYTHING IS COMPARED, and before the
    # marker can excuse it, because the comparison is not the point: whatever
    # the value looks like to the left of the `#`, environ and docker both read
    # the `#` and everything after it AS PART OF THE NAME. A line that "agrees"
    # here is the worst case of the three, not the safe one — it passed
    # silently while a bare `manage.py` opened a different database.
    if [ "$DB_PIN_VERDICT" = "inline" ]; then
        # The value with the comment cut off AND the whitespace that separated
        # them trimmed — printing `djb_x  ` with two trailing spaces as the
        # suggested rewrite would hand the reader a second corrupt line.
        cleaned="${pin%%#*}"
        cleaned="${cleaned%"${cleaned##*[![:space:]]}"}"
        echo "RED: DATABASE_NAME: this checkout's .env line carries an INLINE COMMENT." >&2
        echo "     the line:   $(grep -E '^DATABASE_NAME=' "${root}/.env" | tail -1)" >&2
        echo "     environ reads the name as: [${pin}]" >&2
        echo "   A trailing comment is NOT stripped by the reader a bare \`manage.py\` uses" >&2
        echo "   (django-environ), nor by \`docker --env-file\`. Only a shell \`. .env\` strips" >&2
        echo "   it. So this one line means two different database names depending on who" >&2
        echo "   reads it — which is the exact split brain this leg exists to refuse, and" >&2
        echo "   the old \`# pinned\` instruction is what put it there." >&2
        echo "   REWRITE IT AS TWO LINES in ${root}/.env — the marker on its own line:" >&2
        echo "" >&2
        echo "     # pinned" >&2
        echo "     DATABASE_NAME=${cleaned}" >&2
        echo "" >&2
        echo "   (drop the marker line entirely if the pin was not deliberate, then re-run" >&2
        echo "   ./scripts/setup.sh to reconcile.)" >&2
        return 1
    fi
    if [ "$DB_PIN_VERDICT" = "agree" ]; then
        echo "  .env and the derivation agree: ${derived}"
        db_pin_existence "$mode" "$derived" derived
        return $?
    fi
    if [ "$DB_PIN_VERDICT" = "marked" ]; then
        # Declared deliberate. Silent ABOUT THE PIN by design — see the block
        # above. The existence question is a different question and is still
        # asked: a deliberate name that opens nothing is exactly the shape above,
        # and "I meant this name" is not "this name is there".
        db_pin_existence "$mode" "$pin" ".env pin"
        return $?
    fi
    # Every verdict but one is handled above; a verdict this function has no
    # cell for is the table and its reader disagreeing, which is broken
    # enforcement and never a refusal blamed on the checkout.
    if [ "$DB_PIN_VERDICT" != "disagree" ]; then
        gate_refuse "db-pin: db_pin_decide answered '${DB_PIN_VERDICT}', which db_pin_leg has no cell for."
        return 2
    fi
    echo "RED: DATABASE_NAME: this checkout's .env and its derivation DISAGREE." >&2
    echo "     .env pins:  ${pin}" >&2
    echo "     derivation: ${derived}" >&2
    echo "   A bare \`manage.py\` resolves the pin; every script here sources scripts/db.sh" >&2
    echo "   and resolves the derivation. One checkout, TWO databases — which is how a" >&2
    echo "   migrate and a token mint landed in the owner's live database once already," >&2
    echo "   with every step of it legal and none of it visible." >&2
    echo "   Two fixes, and this leg does not choose between them:" >&2
    echo "     * KEEP THE PIN — add a \`# pinned\` line ABOVE that line in ${root}/.env:" >&2
    echo "" >&2
    echo "         # pinned" >&2
    echo "         DATABASE_NAME=${pin}" >&2
    echo "" >&2
    echo "       Its OWN line, never appended to the value: a trailing comment is read" >&2
    echo "       INTO the name by django-environ and by docker --env-file, so the inline" >&2
    echo "       form this file used to prescribe corrupts the very name it pins." >&2
    echo "       The name stays, setup.sh stops rewriting it, and this leg goes silent." >&2
    echo "     * RECONCILE — re-run ./scripts/setup.sh, which rewrites the line to the" >&2
    echo "       derivation, says which name it overrode, and prepares that database" >&2
    echo "       (it reads this same verdict — db_pin_decide — so it cannot disagree)." >&2
    return 1
}

# --- THE EXISTENCE HALF -----------------------------------------------------
#
# Called by `db_pin_leg` on every path where the PIN COMPARISON PASSED, with the
# mode and the name that comparison concluded is operative. Under `fast` it hands
# off to `db_pin_fast_existence`, which asks of the derived name only.
#
# THE THREE ANSWERS, and the middle one is the whole point:
#
#   the row is there        exit 0, one line naming the database
#   the row is NOT there    exit 2, naming ./scripts/setup.sh — the fix
#   nothing answered        exit 2, naming docker — COULD NOT LOOK
#
# `db_exists` collapses the last two: it swallows psql's stderr and tests for
# the literal `1`, so a stack that is down and a database that is missing are
# the same empty string to it. That collapse is fine for a caller about to
# CREATE the database and fatal for a caller about to JUDGE it — an absent
# database and an absent server are different facts with different fixes, and
# reporting the second as the first would send a reader to `setup.sh` for a
# docker problem. So a negative is re-asked as a reachability question before it
# is reported, and only a reachable server may produce the `does not exist`
# refusal. `db_query 'SELECT 1'` is the same probe `test_db_zsh.sh::live_reachable`
# already uses.
db_reachable() {
    db_query 'SELECT 1' -tA >/dev/null 2>&1
}

# db_pin_effective_name <leg's name> <leg's label> — WHICH database will the run OPEN?
#
# Sets `DB_EFFECTIVE_NAME` and `DB_EFFECTIVE_SOURCE`. It re-decides NOTHING: the
# precedence lives at rule 1's line above (`db_resolve_name`) and is recorded there as `DATABASE_NAME_SOURCE`. This function READS that
# answer — the same `$DATABASE_NAME` every other consumer reads, the one
# `db_exists`, `db_create` and `db_drop` default to and `backup.sh::db_present`
# asks Postgres about — and only falls back to what the pin comparison concluded
# when rule 1 did not override anything.
#
# WHY THE FALLBACK EXISTS AT ALL. With no export there is no third reader to
# disagree with, and the leg's own conclusion is the better-attributed answer: it
# knows whether the name came from the derivation or from a deliberate `# pinned`
# line. So the labels are three, not two — `derived`, `.env pin` (both written by
# `db_resolve_name`) and `DATABASE_NAME exported`.
#
# THE ORDER IS RULE 1'S ORDER AND IT IS NOT NEGOTIABLE HERE: an export wins. It
# is the documented escape (this file's header, rule 1; CLAUDE.md § The schema
# discipline calls it "the only escape"), every script honours it, and a leg that
# reported on a name the run will not open is worse than a leg that says nothing.
#
# THE LABEL IS NOT TRUSTED ON ITS OWN — IT IS CHECKED AGAINST THE DERIVATION.
#
# `DATABASE_NAME_SOURCE` is a HINT: sticky (a child that inherits a derived name
# must not be re-labelled "exported") and inherited across processes, which is
# what makes it useful and what makes it forgeable. Two ways it ends up
# describing a name it was never true of, both measured:
#
#   * SAME PROCESS — source db.sh, then `export DATABASE_NAME=something_else`.
#   * ACROSS A PROCESS — source db.sh (what `setup.sh`'s "Next:" block tells an
#     operator to do), then run `DATABASE_NAME=other ./some_script.sh`. The child
#     gets the label from the parent and the name from the command line.
#
# THE SECOND ONE IS WHY THIS CHECK CANNOT USE ANYTHING RULE 1'S BLOCK RECORDS.
# An earlier version compared the value against a `DATABASE_NAME_RESOLVED` that
# the block wrote beside the label. It closed the same-process case and not the
# cross-process one, because the block runs in the child too and re-recorded the
# name the child was handed — so the pair agreed and the lie was believed. Every
# variable is caller-controlled input; the environment cannot authenticate
# itself.
#
# WHAT CANNOT BE FORGED IS THE CHECKOUT. `db_name` reads git's top level and
# hashes it: it is a property of WHERE THIS TREE IS, not of what anyone
# exported. So the check is `$DATABASE_NAME` against `db_name` — the name the
# `derived` label CLAIMS, computed fresh — and it holds however many shells and
# processes the label crossed to get here.
#
# The `.env pin` label is checked against the marked pin `db_pin_decide` reads now,
# since `db_resolve_name` exported that pin; when it holds, the leg keeps the label
# it was given — `.env pin` stays `.env pin`.
#
# On a mismatch the VALUE wins (rule 1 — what is in the variable is what every
# consumer will resolve), the source is reported as `DATABASE_NAME exported`
# because that is what it is, and `DB_EFFECTIVE_LABEL_STALE` is set so the caller
# can say the quiet part: the label this process inherited was not true here.
db_pin_effective_name() {
    local implied
    DB_EFFECTIVE_LABEL_STALE=""
    if [ "${DATABASE_NAME_SOURCE:-derived}" = "DATABASE_NAME exported" ]; then
        DB_EFFECTIVE_NAME="${DATABASE_NAME}"
        DB_EFFECTIVE_SOURCE="DATABASE_NAME exported"
        return 0
    fi
    # The name the label claims, for THIS checkout, computed now: the marked pin for
    # `.env pin` (what `db_resolve_name` exported), the derivation for `derived`.
    implied="$(db_name)"
    if [ "${DATABASE_NAME_SOURCE:-derived}" = ".env pin" ]; then
        db_pin_decide
        if [ "$DB_PIN_VERDICT" = "marked" ]; then
            implied="$DB_PIN_VALUE"
        fi
    fi
    if [ -n "${DATABASE_NAME:-}" ] && [ "${DATABASE_NAME}" != "${implied}" ]; then
        DB_EFFECTIVE_NAME="${DATABASE_NAME}"
        DB_EFFECTIVE_SOURCE="DATABASE_NAME exported"
        DB_EFFECTIVE_LABEL_STALE=1
        return 0
    fi
    DB_EFFECTIVE_NAME="$1"
    DB_EFFECTIVE_SOURCE="$2"
}

# db_pin_fast_existence <name> <label> — under fast, the derived name alone: present, absent or no server, each said and 0.
db_pin_fast_existence() {
    db_pin_effective_name "$1" "$2"
    if [ "$DB_EFFECTIVE_SOURCE" != "derived" ]; then
        return 0
    fi
    if db_exists "$DB_EFFECTIVE_NAME"; then
        echo "  database ${DB_EFFECTIVE_NAME} exists (derived)"
        return 0
    fi
    if ! db_reachable; then
        echo "  existence not answered: the compose Postgres did not answer (--fast needs no database)"
        return 0
    fi
    echo "  database ${DB_EFFECTIVE_NAME} does not exist (derived) — --fast needs none; ./scripts/setup.sh creates it before --loop"
    return 0
}

db_pin_existence() {
    local mode="$1" name="$2" label="${3:-derived}" rc=0 derivation=""
    # An `if`, not `[ … ] && return 0`: an AND-list whose left half is false
    # returns 1, and under a caller's `set -e` that is the function failing
    # rather than the mode being `loop`.
    if [ "$mode" = "fast" ]; then
        db_pin_fast_existence "$name" "$label"
        return $?
    fi
    # WHICH NAME, AND SAID OUT LOUD. The pin comparison concluded `$name`; rule 1
    # may have overridden it before any of this ran. Resolve, then report BOTH
    # the name and where it came from — an existence verdict that does not name
    # its source cannot be told from one that looked at the wrong database.
    db_pin_effective_name "$name" "$label"
    name="$DB_EFFECTIVE_NAME"
    label="$DB_EFFECTIVE_SOURCE"
    # AND WHEN THE LABEL WAS THE THING THAT WAS WRONG, SAY SO. A reader who sees
    # `DATABASE_NAME exported` on a run they did not export anything in needs to
    # know WHY the leg calls it that, or the line reads as the leg being confused.
    if [ -n "${DB_EFFECTIVE_LABEL_STALE:-}" ]; then
        echo "  note: DATABASE_NAME does not match this checkout's derivation, and the"
        echo "        inherited DATABASE_NAME_SOURCE label still says 'derived' — the label"
        echo "        was set by a shell or a parent process, not by this name. The VALUE"
        echo "        wins (rule 1), so the source is reported as exported."
    fi
    db_exists "$name" || rc=$?
    if [ "$rc" = "0" ]; then
        echo "  database ${name} exists (${label})"
        return 0
    fi
    if ! db_reachable; then
        gate_refuse "the db-pin leg COULD NOT LOOK: the compose Postgres did not answer (docker)."
        echo "   The pin was compared and is fine; whether ${name} (${label}) EXISTS is the" >&2
        echo "   question" >&2
        echo "   that could not be asked, and an unanswered question is not a pass." >&2
        echo "   \`docker compose exec -T db psql\` is how this leg looks, so either docker" >&2
        echo "   is not on PATH or the stack is down:" >&2
        echo "" >&2
        echo "     docker compose up -d db" >&2
        echo "" >&2
        echo "   (\`./scripts/check.sh --fast\` does not ask this question at all —" >&2
        echo "   build-contract.md § Interfaces: --fast needs no database.)" >&2
        return 2
    fi
    # THE REFUSAL NAMES THE SOURCE, AND THE REMEDY FOLLOWS FROM IT. `setup.sh` is
    # the fix for a name this checkout derived; it is NOT the fix for a name an
    # operator handed in, because setup.sh would go and prepare the DERIVED one
    # and leave the override pointing at nothing. Sending a reader to the wrong
    # command is the same defect as naming the wrong database, one step later.
    if [ "$label" = "DATABASE_NAME exported" ]; then
        gate_refuse "this checkout's database ${name} does not exist (DATABASE_NAME exported)"
        echo "   DATABASE_NAME is set in this environment, and rule 1 says an exported name" >&2
        echo "   WINS: every script here, the suite, and this leg all resolve ${name}," >&2
        echo "   whatever .env pins and whatever this checkout would derive. There is" >&2
        echo "   nothing behind that name, so the run would open nothing." >&2
        echo "   \`./scripts/setup.sh\` is NOT the fix — it would prepare the name this" >&2
        echo "   checkout DERIVES and leave the override pointing at nothing. Either:" >&2
        echo "" >&2
        echo "     unset DATABASE_NAME          # fall back to this checkout's own name" >&2
        echo "     DATABASE_NAME=${name} ./scripts/setup.sh   # or prepare the one you meant" >&2
        echo "" >&2
        echo "   The server IS reachable — that was asked before this line was printed —" >&2
        echo "   so the database is genuinely absent." >&2
        return 2
    fi
    # THE `# pinned` CELL HAS ITS OWN REMEDY, BECAUSE THE ORDINARY ONE IS WRONG
    # HERE. A marked pin reaches this function only when the pin and the
    # derivation DIFFER — agreement is handled one branch up, under the `derived`
    # label — so the sentence below ("the pin and the derivation agree") was
    # false on exactly this path, printed directly under a note saying they
    # differ. A bare `./scripts/setup.sh` is the remedy: it sources this file, whose
    # `db_resolve_name` exports the pin, so its `db_create` and migrate take the pin.
    if [ "$label" = ".env pin" ]; then
        derivation="$(db_name)"
        gate_refuse "this checkout's database ${name} does not exist (.env pin)"
        echo "     .env pins:  ${name}   (the \`# pinned\` marker says this name is deliberate)" >&2
        if [ "$name" = "$derivation" ]; then
            echo "     derivation: ${derivation}   — the pin AGREES with the derivation" >&2
        else
            echo "     derivation: ${derivation}   — the pin DIFFERS from the derivation" >&2
        fi
        echo "   A bare \`./scripts/setup.sh\` creates and migrates ${name}: it sources" >&2
        echo "   scripts/db.sh, which resolves the \`# pinned\` name, so every step it runs" >&2
        echo "   opens the pin. Either:" >&2
        echo "" >&2
        echo "     ./scripts/setup.sh   # prepare the name you pinned" >&2
        echo "" >&2
        echo "   or drop the \`# pinned\` line from .env and re-run ./scripts/setup.sh, which" >&2
        echo "   then rewrites the pin to the derivation and prepares that one instead." >&2
        echo "   The server IS reachable — that was asked before this line was printed —" >&2
        echo "   so the database is genuinely absent." >&2
        return 2
    fi
    gate_refuse "this checkout's database ${name} does not exist (${label}) — run ./scripts/setup.sh"
    echo "   The pin and the derivation agree on the NAME and there is nothing behind it." >&2
    echo "   That is not a hypothetical: the bank that paid for this leg ran ten green" >&2
    echo "   minutes — every leg, both pytest passes — and then refused at the selftest" >&2
    echo "   leg because the checkout's database had been swept away hours earlier. This" >&2
    echo "   leg is where those ten minutes are given back." >&2
    echo "" >&2
    echo "     ./scripts/setup.sh" >&2
    echo "" >&2
    echo "   creates and migrates it. The server IS reachable — that was asked before" >&2
    echo "   this line was printed — so the database is genuinely absent." >&2
    return 2
}

# The note that used to be the whole enforcement. It stays, DEMOTED: the leg
# above is what has to be answered, and a script running outside the gate still
# deserves a one-line heads-up rather than a surprise. It points at the leg
# instead of restating the fixes, so there is exactly one place that spells
# them out and it is the one with an exit status.
#
# It reads `db_pin_decide`'s verdict like every other reader of the pin. The
# `inline` cell prints the refusing form whether or not a marker sits above
# the line: the leg refuses an inline comment marked or not, so a note saying
# "(# pinned)" over it would be telling the reader the one thing that is false.
db_announce_pin_disagreement() {
    db_pin_decide
    if [ -n "$DB_PIN_VALUE" ] && db_is_foreign "$DB_PIN_VALUE"; then
        if [ "$DB_PIN_VALUE" != "${DB_FOREIGN_SAID:-}" ]; then
            db_say_foreign "$DB_PIN_VALUE"
        fi
        return 0
    fi
    case "$DB_PIN_VERDICT" in
    marked)
        printf 'note: DATABASE_NAME pinned to %s by .env (# pinned); derivation says %s — every step opens %s\n' \
            "$DB_PIN_VALUE" "$DB_PIN_DERIVED" "$DATABASE_NAME" >&2
        ;;
    disagree | inline)
        printf 'note: DATABASE_NAME pinned to %s by .env; derivation says %s — the gate'"'"'s db-pin leg refuses this (./scripts/check.sh --fast says what to do)\n' \
            "$DB_PIN_VALUE" "$DB_PIN_DERIVED" >&2
        ;;
    esac
    return 0
}
# THE NOTE IS NOT PRINTED WHERE THE CALLER'S OUTPUT IS A TABLE. `check.sh
# --list-legs` sources this file and its whole output is the unit table a CI
# job or a drive reads line by line — and a reader that captures stderr with
# stdout (`test_list_legs.sh` does, so a refusal is never lost) read the note
# as a unit row: `every line is <unit>\t<needs>…` red, a dry `--leg note:…`,
# exit 2, on every checkout whose pin disagrees — `# pinned` included. So the
# caller whose output is data says so, by setting `DB_PIN_NOTE_OFF` in its OWN
# shell before the source (never exported: a child still gets its note). The
# leg is untouched by it — the note is the heads-up, the leg is the
# enforcement, and a listing runs no leg.
if [ -z "${DB_PIN_NOTE_OFF:-}" ]; then
    db_announce_pin_disagreement
fi

POSTGRES_USER="${POSTGRES_USER:-djb}"
export POSTGRES_USER

# Run psql inside the compose container. There is no psql on the host.
db_psql() {
    docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres "$@"
}

# --- Names are not strings ----------------------------------------------------
#
# A database name reaching this file is OPERATOR input — `DATABASE_NAME` out of
# the environment, or an argument — and it used to be pasted into SQL with
# `"${name}"`. A name carrying a quote therefore composed statements: SEC-1
# proved it, and SEC-R3 proved it again by making `db_exists` run a `CREATE
# TABLE` that landed in the server. Nothing here is a privilege boundary — the
# caller already has the psql socket — but a tool whose refusals are described
# in its own header as load-bearing must refuse by CONSTRUCTION, not by luck:
# both of `db_sweep.sh`'s survived only because `psql -c` wraps a multi-statement
# string in one transaction and `DROP DATABASE` will not run in one.
#
# Two layers, and each is sufficient on its own:
#
#   1. `db_valid_name` — a name is `[A-Za-z0-9_]{1,63}` or it is refused before
#      any SQL is built. Every name this repository derives is already that
#      (`db_name` above, Django's `test_` prefix, xdist's `_gwN`), so the gate
#      costs a legitimate caller nothing and turns an injection attempt into a
#      sentence rather than a puzzling Postgres error.
#   2. psql VARIABLES — `:'x'` for a literal, `:"x"` for an identifier. psql
#      does the quoting, so a value is a value however it is spelled. The
#      statement arrives on stdin because `psql -c` sends its argument to the
#      server unparsed and interpolates nothing; `db_query` is that plumbing.
#
# THE SAME CLASS, IN PYTHON:
# `quality/hotpaths.py::guarded_identifier` is this function's twin, byte for
# byte — `[A-Za-z0-9_]`, at most 63 bytes — and `quality/hotpath_probe.py`'s
# `CREATE DATABASE` composes its identifier with `psycopg.sql.Identifier`, which
# is layer 2 on that side. It was found protected by the SAME accident this
# header describes (a multi-statement DDL string cannot run in psycopg's
# implicit transaction either), which is why it is now guarded rather than
# lucky. Two languages, one rule: change it here and there, and nowhere else.
db_valid_name() {
    local name="${1:-}"
    [ -n "$name" ] || return 1
    [ "${#name}" -le 63 ] || return 1
    # In a subshell with the C locale: a glob range under a UTF-8 collation can
    # match letters nobody typed, and this file may not change the caller's env.
    (
        LC_ALL=C
        case "$name" in
        *[!A-Za-z0-9_]*) exit 1 ;;
        esac
        exit 0
    )
}

db_refuse_name() {
    printf '!! refusing the database name %s\n' "$(printf '%q' "${1:-}")" >&2
    printf '   a database name here is [A-Za-z0-9_], at most 63 bytes — the shape this\n' >&2
    printf '   repository derives. Nothing legitimate is outside it (scripts/db.sh).\n' >&2
}

# Send SQL on stdin so psql interpolates the `:'x'` / `:"x"` variables in it.
db_query() {
    local sql="$1"
    shift
    printf '%s' "$sql" | db_psql "$@"
}

db_exists() {
    local name="${1:-$DATABASE_NAME}"
    local found
    if ! db_valid_name "$name"; then
        db_refuse_name "$name"
        return 2
    fi
    found="$(db_query "SELECT 1 FROM pg_database WHERE datname = :'name'" \
        -v name="$name" -tA 2>/dev/null || true)"
    [ "$found" = "1" ]
}

db_create() {
    local name="${1:-$DATABASE_NAME}"
    if ! db_valid_name "$name"; then
        db_refuse_name "$name"
        return 2
    fi
    if db_exists "$name"; then
        echo "database ${name} already exists"
        return 0
    fi
    # THE ONE NAME THAT GETS THE TEMPLATE — see THE TEMPLATE DATABASE below for
    # why it is one name and not all of them. Every other name falls through to
    # the plain CREATE this function has always done, byte for byte.
    if db_template_wanted "$name"; then
        db_create_the_checkouts_own "$name"
        return $?
    fi
    db_query 'CREATE DATABASE :"name" OWNER :"owner"' \
        -v name="$name" -v owner="$POSTGRES_USER" >/dev/null || return 1
    echo "created database ${name}"
}

db_drop() {
    local name="${1:-$DATABASE_NAME}"
    if ! db_valid_name "$name"; then
        db_refuse_name "$name"
        return 2
    fi
    if ! db_exists "$name"; then
        echo "database ${name} does not exist"
        return 0
    fi
    db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$name" >/dev/null
    echo "dropped database ${name}"
    # Django's test database for this checkout, if it was left behind.
    if db_exists "test_${name}"; then
        db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="test_${name}" >/dev/null
        echo "dropped database test_${name}"
    fi
}

# =============================================================================
# THE TEMPLATE DATABASE
# =============================================================================
#
# WHAT IT IS FOR. Every worktree on this machine used to pay the whole migration
# chain to get an empty schema — measured at 17.00s in this checkout's own
# `rung_start.sh` run, and paid again by every one of the nine worktrees a wave
# spawns. The schema is IDENTICAL in all of them, because it is a pure function
# of the migration set. So it is built once, into a machine-global template, and
# every checkout after that gets its database with
#
#     CREATE DATABASE <mine> TEMPLATE djb_tmpl_<key>
#
# which is a file copy: seconds, no Django, no Python.
#
# THE KEY IS DERIVED AND NEVER TYPED. `djb_tmpl_<16 hex>` where the hex is a
# digest of the MIGRATION FILES THEMSELVES — this checkout's `apps/*/migrations/`
# and the third-party ones in its own `.venv` — so it moves when a migration is
# added, changed or removed and for nothing else. A hand-bumped version number
# is the drift class the whole rules engine exists against: somebody forgets to
# bump it and every checkout on the machine quietly gets last week's schema.
# `quality/tests/test_db.py` drives both directions of that iff.
#
# THE KEY IS THE SAME IN EVERY CHECKOUT, and this is the one place in this file
# where that is the goal. `db_name` above deliberately does the opposite: the
# name follows the CHECKOUT so two clones never share a database. The
# template is the other kind of object: it is shared ON PURPOSE, it is read-only
# by construction, and a key that varied by path would give every worktree its
# own template and save nobody anything. The digest is taken over paths
# normalised to `apps/...` and `site-packages/...`, which is what makes two
# checkouts at different absolute paths agree.
#
# ONE NAME GETS IT, AND ONLY ONE. `db_create` uses the template ONLY for the
# database this checkout DERIVES for itself — `name = db_name`. Every other
# caller is creating a database it is about to fill itself and a populated one
# would break it outright: `scripts/restore_drill.sh` pg_restores a dump into
# what `db_create` hands back (`--exit-on-error` over existing relations), and
# `scripts/perf.sh` creates its `_perf` world. Their output does not change
# either — the `path=` line below is printed only on the one name. That is also
# why the rule is DERIVED (a name equal to `db_name`) rather than a list of
# names to skip: a list is a thing that goes stale when a seventh caller arrives.
#
# A MISS IS LOUD AND IS NOT AN ERROR. No template for this migration set means a
# plain empty database and the caller's `migrate` running the whole chain —
# exactly what happened before this block existed. It says so, names the one
# command that publishes the template, and exits 0. Nothing here ever refuses to
# create a database because a template was missing.
#
# CONCURRENCY, DRIVEN RATHER THAN ARGUED. Postgres refuses
# `CREATE DATABASE ... TEMPLATE t` while any session is connected to `t`:
#
#     ERROR:  source database "djb_probe_open" is being accessed by other users
#     DETAIL:  There is 1 other session using the database.
#
# So a published template ALLOWS NO CONNECTIONS (`ALTER DATABASE ...
# ALLOW_CONNECTIONS false`) — the same construction `template0` uses. With no
# session able to exist, the refusal has nothing to count: six concurrent clones
# of one no-connections template were driven and all six succeeded
# with identical contents (`quality/tests/test_db.py::
# test_concurrent_clones_of_one_template_all_succeed_uncorrupted`). `db_clone_database` still
# retries that exact refusal and still falls back loudly, because the template
# can also be dropped or superseded between the existence check and the clone,
# and a mechanism whose safety rests on one ALTER having been run is a mechanism
# with a single point of silence.
#
# PUBLICATION IS ATOMIC, so a half-migrated template cannot be observed. The
# refresh migrates a uniquely named SCRATCH database and then publishes it with
# one `CREATE DATABASE djb_tmpl_<key> TEMPLATE <scratch>`. Two checkouts
# refreshing at once each build their own scratch; the first to publish wins and
# the second is told so and uses the winner's. The published name only ever
# comes into existence fully migrated.
#
# WHAT THIS DOES NOT SEE, declared:
#
#   1. The key digests MIGRATION FILES, not the schema. `INSTALLED_APPS`, the
#      settings module, and a `RunPython` whose behaviour depends on something
#      outside its own file are all outside it. The net is unchanged and it is
#      the caller's: every consumer runs `migrate` after `db_create` and
#      `rung_start.sh` then runs `migrate --check`, so a template that is behind
#      is caught and topped up rather than trusted.
#   2. It cannot notice a template that is AHEAD — a schema carrying a migration
#      this tree no longer has. The key moves when a migration file is removed,
#      so the only way in is two different trees whose migration files digest
#      the same, which is what the 16 hex digits are for.
#   3. `db_template_refresh` PRUNES the superseded templates it can see. On a
#      machine where two checkouts on different branches both refresh, they will
#      take turns dropping each other's template and both will fall back loudly
#      until one stops. That is the deliberate trade against an unbounded
#      population of machine-global databases nothing sweeps, and the refresh is
#      the merge path's — which runs on one branch.
#   4. A checkout whose `DATABASE_NAME` is PINNED (rule 1 above) never takes the
#      template path, because the pin is not `db_name`. A pinned checkout keeps
#      exactly the behaviour it had.

# The clock is the seam's (`gate_refuse.sh::clock_ms`); a copy of this file sourced without its seam times in whole seconds.
db_now_ms() {
    if command -v clock_ms >/dev/null 2>&1; then
        clock_ms
    else
        printf '%s000' "$(date +%s)"
    fi
}

db_elapsed_since() {
    awk -v ms="$(($(db_now_ms) - $1))" 'BEGIN { printf "%.2fs", ms / 1000 }'
}

db_digest_files_0() {
    case "$(db_digest_tool)" in
    shasum) xargs -0 shasum -a 256 ;;
    sha256sum) xargs -0 sha256sum ;;
    *) return 1 ;;
    esac
}

# `<digest>  <normalised path>` for every migration file this checkout would
# load, sorted. Prints nothing and returns 1 when there is no digest tool or no
# migration file at all — an empty digest would be one key every empty tree
# shared, which is the one collision that could actually happen.
db_migration_listing() {
    local root="${1:-$(db_checkout_root)}" tmp
    db_digest_tool >/dev/null || return 1
    tmp="$(mktemp "${TMPDIR:-/tmp}/djb-migset.XXXXXX")" || return 1
    {
        [ -d "${root}/apps" ] && find "${root}/apps" -type f -path '*/migrations/*.py' -print0
        [ -d "${root}/.venv" ] && find "${root}/.venv" -type f -path '*/migrations/*.py' -print0
        true
    } >"$tmp" 2>/dev/null
    if [ ! -s "$tmp" ]; then
        rm -f "$tmp"
        return 1
    fi
    # The two normalisations that make the key checkout-independent, and they
    # are anchored on the two spaces the digest tools put between hash and path
    # so nothing in a directory name can be mistaken for the separator. The
    # checkout root is never interpolated into the expression — a root carrying
    # a `#` would otherwise rewrite the script.
    db_digest_files_0 <"$tmp" |
        sed -e 's#  .*/site-packages/#  site-packages/#' -e 's#  .*/apps/#  apps/#' |
        LC_ALL=C sort
    rm -f "$tmp"
}

# The template key: 16 hex over that listing. Returns 1 when the listing does.
db_migration_key() {
    local listing
    listing="$(db_migration_listing "$(db_checkout_root)")" || return 1
    [ -n "$listing" ] || return 1
    db_path_hash "$listing" 16
}

db_template_name() {
    local key
    key="$(db_migration_key)" || return 1
    printf 'djb_tmpl_%s' "$key"
}

# Is THIS the name that gets the template? Derived, never listed: the one
# database this checkout makes for itself. `DJB_DB_TEMPLATE=off` is the escape,
# and it is the same shape as `DATABASE_NAME`'s — an environment variable that
# turns a derivation off without editing anything.
db_template_wanted() {
    local name="${1:-}"
    [ "${DJB_DB_TEMPLATE:-on}" != "off" ] || return 1
    [ -n "$name" ] || return 1
    [ "$name" = "$(db_name)" ] || return 1
    return 0
}

# CREATE DATABASE <new> TEMPLATE <src>, retrying the one refusal Postgres raises
# for a template somebody is using. Prints the server's own words on the way out
# — a paraphrase of a Postgres error is how a caller ends up debugging the
# paraphrase.
db_clone_database() {
    local new="${1:-}" src="${2:-}" out=""
    local attempts="${DB_TEMPLATE_CLONE_ATTEMPTS:-5}"
    local backoff="${DB_TEMPLATE_CLONE_BACKOFF:-1}"
    local n=1
    if ! db_valid_name "$new"; then
        db_refuse_name "$new"
        return 2
    fi
    if ! db_valid_name "$src"; then
        db_refuse_name "$src"
        return 2
    fi
    while :; do
        # `if !` and not `set +e`: this file may not change the caller's shell
        # options, and a bare failing command under a caller's `set -e` would
        # take the whole script down inside a function whose entire job is to
        # fail survivably.
        if out="$(db_query 'CREATE DATABASE :"new" TEMPLATE :"src" OWNER :"owner"' \
            -v new="$new" -v src="$src" -v owner="$POSTGRES_USER" 2>&1)"; then
            return 0
        fi
        case "$out" in
        *"being accessed by other users"*)
            if [ "$n" -lt "$attempts" ]; then
                printf 'db.sh: template %s is momentarily in use — retrying (%d/%d)\n' \
                    "$src" "$n" "$attempts" >&2
                sleep "$backoff"
                n=$((n + 1))
                continue
            fi
            ;;
        esac
        printf '%s\n' "$out" >&2
        return 1
    done
}

# The one name that gets the template path. Always prints the instrument line —
# `path=` and `elapsed=` — whichever way it went, because a mechanism whose
# speed claim is a builder's stopwatch is a claim nobody else can re-measure.
db_create_the_checkouts_own() {
    # `creation_path` and NOT `path`: under zsh `path` is tied to PATH and
    # `local` does not untie it, so the old name emptied PATH for the length of
    # this function — docker, awk and date all vanished and `created database`
    # printed over a database that was never created. THE SOURCED-LIBRARY
    # CONTRACT at the top of this file has the reproduction and the closed
    # audit; `quality/tests/test_db.py` is the tooth. The PRINTED token
    # stays `path=` — that string is the instrument's contract with its readers
    # (`quality/tests/test_db.py` reads it); only the shell
    # variable was ever the bug.
    local name="$1" t0 key tmpl="" creation_path=fallback reason=""
    t0="$(db_now_ms)"
    key="$(db_migration_key 2>/dev/null || true)"
    if [ -z "$key" ]; then
        reason="this checkout's migration set could not be digested (no sha256 tool on PATH, or no migration files under apps/)"
    else
        tmpl="djb_tmpl_${key}"
        if db_exists "$tmpl"; then
            if db_clone_database "$name" "$tmpl"; then
                creation_path=template
            else
                reason="${tmpl} is on this server and could not be cloned — the server's own words are above"
            fi
        else
            reason="no ${tmpl} on this server for this checkout's migration set"
        fi
    fi
    if [ "$creation_path" = fallback ]; then
        if ! db_query 'CREATE DATABASE :"name" OWNER :"owner"' \
            -v name="$name" -v owner="$POSTGRES_USER" >/dev/null; then
            printf 'db.sh: db_create %s path=fallback FAILED — the server refused the CREATE (its words are above)\n' "$name" >&2
            return 1
        fi
    fi
    # The line every caller reads, unchanged and first.
    echo "created database ${name}"
    printf 'db.sh: db_create %s path=%s elapsed=%s\n' "$name" "$creation_path" "$(db_elapsed_since "$t0")"
    if [ "$creation_path" = template ]; then
        printf 'db.sh: cloned from %s — the migration chain did not run; the caller'\''s\n' "$tmpl"
        printf '       `migrate` has nothing left to apply.\n'
    else
        printf 'db.sh: TEMPLATE MISS — %s.\n' "$reason"
        printf '       This database is EMPTY, the caller'\''s `migrate` runs the whole chain,\n'
        printf '       and that is exactly what happened before the template existed. Nothing\n'
        printf '       is wrong here; it is slow. Publish the template for this migration set\n'
        printf '       once and every checkout on this machine clones it after that:\n'
        printf '         bash -c '\''. scripts/db.sh && db_template_refresh'\''\n'
    fi
    return 0
}

# Drop every PUBLISHED template that is not the one being kept. Build scratches
# (`djb_tmpl_<key>_mk<6 hex>`) are deliberately outside the pattern: one of them
# is another checkout's refresh in flight. A drop that Postgres refuses is not a
# failure of this function — the template is in use, which is the one state in
# which not dropping it is right.
db_template_prune() {
    local keep="${1:-}" name
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        [ "$name" != "$keep" ] || continue
        db_valid_name "$name" || continue
        if db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$name" >/dev/null 2>&1; then
            printf 'db.sh: dropped the superseded template %s\n' "$name"
        fi
    done <<EOF
$(db_query "SELECT datname FROM pg_database WHERE datname ~ '^djb_tmpl_[0-9a-f]{16}\$'" -tA 2>/dev/null || true)
EOF
}

# THE REFRESH HOOK. Publish the template for this checkout's migration set, if
# it is not already published. Idempotent, and cheap to call when nothing has
# changed — which is what lets the merge path call it unconditionally.
#
#   exit 0  the template for this migration set is published (by this call or
#           already, or by another checkout that won the race)
#   exit 1  the scratch was built and `migrate` failed against it — nothing was
#           published, and migrate's own transcript is on stderr
#   exit 2  could not look: no digestible migration set, no `uv`, or the scratch
#           could not be created
db_template_refresh() {
    local root listing key tmpl scratch count t0 out
    t0="$(db_now_ms)"
    root="$(db_checkout_root)"
    if ! listing="$(db_migration_listing "$root")" || [ -z "$listing" ]; then
        echo "!! db_template_refresh: this checkout's migration set could not be digested." >&2
        echo "   Either there is no sha256 tool on PATH or there are no migration files" >&2
        echo "   under ${root}/apps. Nothing was created (scripts/db.sh)." >&2
        return 2
    fi
    key="$(db_path_hash "$listing" 16)"
    count="$(printf '%s\n' "$listing" | wc -l | tr -d ' ')"
    tmpl="djb_tmpl_${key}"
    if db_exists "$tmpl"; then
        printf 'db.sh: %s is already published (%s migration files) — nothing to build.\n' "$tmpl" "$count"
        db_template_prune "$tmpl"
        return 0
    fi
    if ! command -v uv >/dev/null 2>&1; then
        echo "!! db_template_refresh: no \`uv\` on PATH, and the template is built by" >&2
        echo "   running this checkout's own \`manage.py migrate\` against a scratch" >&2
        echo "   database. Nothing was created (scripts/db.sh)." >&2
        return 2
    fi
    scratch="djb_tmpl_${key}_mk$(db_path_hash "$$-${RANDOM:-0}-$(date +%s)" 6)"
    if ! db_valid_name "$scratch"; then
        db_refuse_name "$scratch"
        return 2
    fi
    printf 'db.sh: building %s from %s migration files, through a scratch database.\n' "$tmpl" "$count"
    if ! db_query 'CREATE DATABASE :"name" OWNER :"owner"' \
        -v name="$scratch" -v owner="$POSTGRES_USER" >/dev/null 2>&1; then
        echo "!! db_template_refresh: could not create the scratch database ${scratch}." >&2
        return 2
    fi
    # The scratch is migrated through THIS checkout's venv and settings, which is
    # the same `migrate` every consumer would have run for itself. An exported
    # DATABASE_NAME wins over `.env` (django-environ's read_env does not
    # overwrite the environment), which is the same seam
    # `scripts/rung_start.sh:469` and `scripts/perf.sh` already rely on.
    if ! out="$(cd "$root" && DATABASE_NAME="$scratch" uv run python manage.py migrate --no-input 2>&1)"; then
        printf '%s\n' "$out" >&2
        echo "!! db_template_refresh: migrate failed against the scratch ${scratch}." >&2
        echo "   NOTHING WAS PUBLISHED — the template a half-migrated scratch would have" >&2
        echo "   become is the one object on this machine every checkout would then copy." >&2
        db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$scratch" >/dev/null 2>&1 || true
        return 1
    fi
    # PUBLICATION, and it is one statement on purpose (see the block above).
    if db_clone_database "$tmpl" "$scratch"; then
        db_query 'ALTER DATABASE :"name" ALLOW_CONNECTIONS false' -v name="$tmpl" >/dev/null 2>&1 || true
        printf 'db.sh: published %s in %s — every checkout on this machine with this\n' \
            "$tmpl" "$(db_elapsed_since "$t0")"
        printf '       migration set now clones it instead of migrating.\n'
    elif db_exists "$tmpl"; then
        printf 'db.sh: another checkout published %s first — using theirs, dropping mine.\n' "$tmpl"
    else
        echo "!! db_template_refresh: the scratch migrated and could not be published." >&2
        db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$scratch" >/dev/null 2>&1 || true
        return 1
    fi
    db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$scratch" >/dev/null 2>&1 || true
    db_template_prune "$tmpl"
    db_exists "$tmpl"
}

# THE MERGE PATH'S CALL. Same refresh, ADVISORY: it never fails, never changes
# a caller's exit status, and says nothing at all when it cannot look. That
# combination is deliberate and each half has a reason.
#
#   * NEVER FAILS, because the caller is `scripts/pm_merge.sh` and a merge that
#     already happened must not be reported red by a cache warmer. The template
#     is an optimisation; the merge is the work.
#   * SAYS NOTHING WHEN IT CANNOT LOOK, because the same script runs inside
#     `quality/tests/test_merge.py`'s scratch repositories — no `apps/`, no
#     compose stack, no Postgres — and a warmer that printed a docker error into
#     every one of that drive's cases would be teaching a reader to skip output.
#
# It is called at the MERGE and not at rung start on purpose: a builder mid-rung
# has a migration set that exists only in their worktree, and building a
# machine-global template for it would leave one behind per in-flight rung.
# Merged states are the ones every checkout is about to want.
db_template_refresh_advisory() {
    db_query 'SELECT 1' -tA >/dev/null 2>&1 || return 0
    db_migration_listing "$(db_checkout_root)" >/dev/null 2>&1 || return 0
    command -v uv >/dev/null 2>&1 || return 0
    db_template_refresh || true
    return 0
}
