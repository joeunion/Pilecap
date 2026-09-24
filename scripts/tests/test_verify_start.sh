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
# drives: .env.example .gitignore docs/product manage.py pyproject.toml scripts/archaeology_lib.sh scripts/db.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/githooks scripts/kill_mine.sh scripts/loop_tier.sh scripts/queue_cited.sh scripts/sweep.sh scripts/verifier_box.sh scripts/verify_start.sh
# cites: scripts/check.sh
# The drive for `scripts/verify_start.sh` — the verifier-start instrument.
#
#   ./scripts/tests/test_verify_start.sh          run every case
#   ./scripts/tests/test_verify_start.sh --list   name them and stop
#
# WHY IT EXISTS. `verify_start.sh` is made of one clone and three guards, and
# every one of the guards is invisible when it is right: the dirty-source
# refusal, the verdict-key refusal, and the rule that the derivation is ASKED
# FOR rather than copied. The verdict-key guard is the one that has to be
# driven hardest, because the thing it refuses — an untracked file nobody
# thought about — is by construction a thing nobody thought about. It has
# already been paid for twice, in two products, in the same week: a sibling's
# verifier scratch files, and this repository's own untracked
# `.claude/settings.json`, which is why a push once went around the merge
# ritual by hand (`docs/product/misses.md`, the push-ritual entry).
#
# IT BUILDS ITS OWN REPOSITORIES, and it plants nothing in this tree. A scratch
# source repository under `mktemp -d` with a `main`, a rung branch, a
# `.gitignore`, an `.env.example` and a copy of `scripts/db.sh` is a checkout as
# far as this instrument is concerned, and the clone it makes is a real clone.
#
# THE STRAY IS PLANTED, NOT FOUND — twice, from two directions:
#
#   * `case_a_planted_stray_in_the_clone_is_refused_by_name` runs the happy
#     path, writes a file into the finished clone the way a verifier writes a
#     scratch note, and requires `--check` to refuse it BY NAME at exit 2.
#   * `case_a_repository_that_does_not_ignore_dotenv_is_refused_at_step_4`
#     drives the same guard INLINE, in the run's own step 4, over a source
#     repository whose `.gitignore` is missing the `.env` line. The file the
#     guard names there is the one the script itself just wrote, which is the
#     script's own declared blind spot 4 asserted as behaviour rather than
#     left as a sentence.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. THE DATABASE AND THE SCHEMA, AND A REAL `uv sync`. The instrument does
#      not create the database (its header's blind spot 2), so neither does
#      this: what is driven is that the database NAME is derived by the clone's
#      own `scripts/db.sh` and equals what that file independently answers —
#      the seam, not the arithmetic. The VENV it now does provision, and this
#      drive proves the STEP rather than `uv` — a `uv` shim first on PATH
#      records its argv and writes the `.dist-info` directories the loop
#      ledger's environment census counts (the `bin/docker` shape in
#      `test_setup_env.sh`). No real sync runs in a case, so a `uv` that
#      resolves differently, a lockfile that has drifted, or a wheel that will
#      not build are outside what is asserted here; the belt for those is a
#      verifier's own first `--loop` in a real clone.
#   2. A COPY IS WHAT RUNS, in every case but the two that need no root (the
#      pipe refusal and the unknown-option refusal, which run THIS TREE'S OWN
#      FILE). `verify_start.sh` derives its root from its own location, so
#      driving it against a scratch repository means copying it in. The copy is
#      made from this tree's file at the start of every case, so it cannot
#      drift within a run — but it is a copy, and a reader should know it.
#   3. THE REAL ZITADEL. The carry is driven as a FILE OPERATION with a value
#      this drive invented: the announced key names appear, the value never
#      does, and the value lands in the clone's `.env`. Whether the credential
#      works against a live instance is not this drive's claim and is not the
#      instrument's either (its blind spot 5).
#   4. A HOSTILE `.env`. Lines are carried verbatim. A `ZITADEL_*` line with a
#      newline in it, or a value that is itself an assignment, is outside what
#      is driven here.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_verify_start: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble, opted into. On bash 3.2 a `set -u` death hands the
# EXIT trap a status of 0, so a drive that dies halfway reads as a PASS to
# check.sh. Every case below is worthless without this.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_verify_start: $*" >&2
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
    echo "!! unknown argument '$1': test_verify_start.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
# EITHER SPELLING, because the machine is part of the subject. `shasum -a 256`
# is macOS's and `sha256sum` is a minimal Linux's, and this drive has to run on
# both: on a verifier box the bare `shasum` calls below died
# `shasum: command not found` at line 454 and took the whole drive to exit 127
# on the first bank on boxes. Resolved HERE rather than borrowed from
# `sha256_of` — a drive that models a library with the library asserts nothing;
# the same argument `test_setup_env.sh::digest_stdin` and
# `test_loop_ledger.sh::hex64` are written for.
command -v shasum >/dev/null 2>&1 || command -v sha256sum >/dev/null 2>&1 ||
    cannot_look "neither shasum nor sha256sum is on PATH — the read-only assertions below are digests"
digest_stdin() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 | awk '{print $1}'
    else
        sha256sum | awk '{print $1}'
    fi
}
[ -x scripts/verify_start.sh ] ||
    cannot_look "scripts/verify_start.sh is not an executable file in this tree — there is nothing to drive"
[ -r scripts/db.sh ] ||
    cannot_look "scripts/db.sh is not readable — the derivation seam this instrument consumes is not here"

ROOT="$PWD"
REAL="${ROOT}/scripts/verify_start.sh"
REAL_DB="${ROOT}/scripts/db.sh"

# The step count, ASKED rather than typed. A case that spells the total by hand
# goes vacuous the day a step is added — the exact way `says_not "step 1/4"`
# went vacuous in the sibling drive.
STEP_TOTAL_IN_SCRIPT="$(sed -n 's/^STEP_TOTAL=\([0-9][0-9]*\).*/\1/p' "$REAL" | head -1)"
[ -n "$STEP_TOTAL_IN_SCRIPT" ] ||
    cannot_look "scripts/verify_start.sh declares no STEP_TOTAL — the step banners cannot be read"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-verify-start-drive.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

CURRENT=""
RC=0
OUT=""
N=0
SRC=""
DEST=""

# --- THE `uv` SHIM ------------------------------------------------------------
#
# THE SHIM IS THE POINT, and the shape is `test_setup_env.sh`'s stub `docker`.
# A real `uv sync --frozen` in a scratch repository with no `pyproject.toml`
# would be could-not-look on every machine, and a real one in a repository WITH
# one would put a dependency resolution on the per-push wall for a property that
# is not about `uv` at all. So `uv` is a script first on PATH that RECORDS every
# invocation in order — the log IS the sequence, which is what lets a case
# assert that the sync ran BEFORE the seed — and that writes exactly the thing
# the loop ledger's environment census counts: `*.dist-info` directories under
# `.venv`, at the depth `loop_env_fingerprint`'s `find -maxdepth 4` reaches.
#
# WHAT THE SHIM IS NOT ALLOWED TO BE is a `.venv` the drive plants directly.
# The claim under test is that THE STEP provisions it; a drive that made the
# directory itself would be green with the step deleted.
UV_SHIM_DIR="${WORK}/bin"
UV_LOG=""
UV_RC=0

plant_the_uv_shim() {
    mkdir -p "$UV_SHIM_DIR"
    cat >"${UV_SHIM_DIR}/uv" <<'UVSHIM'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_UV_LOG"
echo "uv-shim invoked: $*"
case "$*" in
*sync*)
    if [ "${DJB_DRIVE_UV_RC:-0}" -ne 0 ]; then
        echo "uv-shim: this sync was asked to fail by the drive" >&2
        exit "${DJB_DRIVE_UV_RC}"
    fi
    site=".venv/lib/python3.12/site-packages"
    mkdir -p "${site}/django-5.2.0.dist-info" "${site}/pytest-8.4.2.dist-info"
    printf 'Name: django\nVersion: 5.2.0\n' >"${site}/django-5.2.0.dist-info/METADATA"
    printf 'Name: pytest\nVersion: 8.4.2\n' >"${site}/pytest-8.4.2.dist-info/METADATA"
    ;;
esac
exit 0
UVSHIM
    chmod +x "${UV_SHIM_DIR}/uv"
}
plant_the_uv_shim

# The carried value. It is this drive's invention and it never leaves the
# scratch directory; what the cases assert about it is that the instrument
# PRINTS THE KEY NAME AND NOT THIS STRING.
CARRY_VALUE="drive-invented-not-a-credential-0000"

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then
        sed 's/^/             | /' "$OUT" | tail -30
    fi
    FAILED=$((FAILED + 1))
}

exits() {
    if [ "$RC" -eq "$1" ]; then
        ok "exit ${RC}"
    else
        bad "wanted exit $1, got ${RC}"
    fi
}

says() {
    if grep -qF -- "$1" "$OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}

# An exact-value assertion, for the cases that compare a sha or a count rather
# than look for a sentence.
is() {
    if [ "$1" = "$2" ]; then
        ok "$3 is '$2'"
    else
        bad "$3: wanted '$2', got '$1'"
    fi
}

says_not() {
    if grep -qF -- "$1" "$OUT"; then
        bad "says \"$1\" and must not"
    else
        ok "does not say \"$1\""
    fi
}

# --- the scratch source repository -------------------------------------------
#
# `main` with two commits, a rung branch with one of its own, and main moved on
# afterwards so the union is a REAL merge rather than a fast-forward. The
# `.gitignore` is this template's own Env and run-log lines, because the
# instrument's blind spot 4 is precisely about a repository that lacks them —
# and one case below builds exactly that repository on purpose.
#
#   $1 — "ignores-dotenv" (the normal shape) or "bare-gitignore" (blind spot 4)
#        or "no-gitignore" (nothing ignored at all).
#   $2 — "moved-on" (the default: main moved after the rung branch, so the union
#        is a real merge commit) or "already-up-to-date" (the rung branch
#        already contains main's tip, which is the ONE shape in which a seeded
#        loop row can hit — the instrument's own blind spot 6 says so).
fresh_source() {
    local shape="${1:-ignores-dotenv}"
    local union="${2:-moved-on}"
    UV_RC=0
    N=$((N + 1))
    SRC="${WORK}/src${N}"
    drive_require_scratch SRC "${SRC:-}"
    mkdir -p "${SRC}/scripts"
    git -C "$SRC" init -q
    git -C "$SRC" symbolic-ref HEAD refs/heads/main
    git -C "$SRC" config user.email drive@example.invalid
    git -C "$SRC" config user.name "verify start drive"
    # The real files, copied in — see blind spot 2.
    cp "$REAL" "${SRC}/scripts/verify_start.sh"
    chmod +x "${SRC}/scripts/verify_start.sh"
    cp "$REAL_DB" "${SRC}/scripts/db.sh"
    # The loop ledger and its refusal seam. The python-dependencies step proves
    # the venv by ASKING `loop_env_fingerprint` — the function the first `--loop`
    # will call — rather than re-censusing `.venv` itself, so the clone needs
    # both files or that step is could-not-look by design.
    cp "${ROOT}/scripts/gate_ledger.sh" "${SRC}/scripts/gate_ledger.sh"
    cp "${ROOT}/scripts/gate_refuse.sh" "${SRC}/scripts/gate_refuse.sh"
    case "$shape" in
    ignores-dotenv)
        # `.venv/` is here for the same reason `.env` is: this template ignores
        # both (`.gitignore`, the Env block and line 7), and the clone now has a
        # venv in it. A fixture that ignored one and not the other would be a
        # checkout no product has.
        printf '.env\n.env.*\n!.env.example\n*.log\n.venv/\n' >"${SRC}/.gitignore"
        git -C "$SRC" add .gitignore
        ;;
    bare-gitignore)
        # `*.log` ignored, `.env` NOT — the instrument's declared blind spot 4.
        printf '*.log\n' >"${SRC}/.gitignore"
        git -C "$SRC" add .gitignore
        ;;
    no-gitignore) ;;
    esac
    # The scanner reads this whole literal as one high-entropy base64 run
    # because of the escapes. It is a two-line fixture `.env.example` whose
    # identity key is DELIBERATELY EMPTY — an empty value is the negative case
    # two cases below depend on, so there is nothing here to leak.
    printf 'DATABASE_NAME=djb_placeholder\nZITADEL_PAT=\n' >"${SRC}/.env.example" # pragma: allowlist secret
    echo "one" >"${SRC}/tracked.txt"
    git -C "$SRC" add scripts/verify_start.sh scripts/db.sh scripts/gate_ledger.sh \
        scripts/gate_refuse.sh .env.example tracked.txt
    git -C "$SRC" commit -q -m "base"
    git -C "$SRC" checkout -q -b rung-x
    echo "what the rung built" >"${SRC}/rung.txt"
    git -C "$SRC" add rung.txt
    git -C "$SRC" commit -q -m "the rung"
    git -C "$SRC" checkout -q main
    echo "two" >>"${SRC}/tracked.txt"
    git -C "$SRC" add tracked.txt
    git -C "$SRC" commit -q -m "main moved on afterwards"
    if [ "$union" = "already-up-to-date" ]; then
        # The builder's last fold, modelled: the rung branch carries main's tip,
        # so step 2 takes its *already up to date* arm and the union IS the
        # branch tip — the same sha in every clone this drive makes of it, which
        # is what lets one case derive a key in one clone and look it up in the
        # next.
        git -C "$SRC" checkout -q rung-x
        git -C "$SRC" -c user.email=drive@example.invalid -c user.name="verify start drive" \
            merge -q --no-edit main
        git -C "$SRC" checkout -q main
    fi
}

# The primary's `.env` — the thing the ZITADEL carry reads. Never committed:
# a `.env` in a repository is the disease, not the fixture.
source_env() {
    printf '%s\n' "$@" >"${SRC}/.env"
}

# Run the COPY, from inside the scratch source repository, capturing both
# streams. The destination is always outside the source.
run_it() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    DEST="${WORK}/clone${N}"
    UV_LOG="${WORK}/uv${N}.log"
    : >"$UV_LOG"
    RC=0
    (
        cd "$SRC" || exit 2
        export PATH="${UV_SHIM_DIR}:$PATH"
        export DJB_DRIVE_UV_LOG="$UV_LOG"
        export DJB_DRIVE_UV_RC="$UV_RC"
        ./scripts/verify_start.sh "$@" "$DEST"
    ) >"$OUT" 2>&1 || RC=$?
}

# Run the copy with an explicit argument list and NO appended destination.
run_raw() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    UV_LOG="${WORK}/uv${N}.log"
    : >"$UV_LOG"
    RC=0
    (
        cd "$SRC" || exit 2
        export PATH="${UV_SHIM_DIR}:$PATH"
        export DJB_DRIVE_UV_LOG="$UV_LOG"
        export DJB_DRIVE_UV_RC="$UV_RC"
        ./scripts/verify_start.sh "$@"
    ) >"$OUT" 2>&1 || RC=$?
}

# =============================================================================

# Runs THIS TREE'S OWN FILE: the pipe refusal fires before the script derives a
# root or reads an argument, so it needs no scratch repository at all.
case_a_piped_stdout_is_refused() {
    CURRENT="a piped stdout is refused"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    # The pipe is the point. `cat` is the filter whose exit status would
    # otherwise become the verdict, and PIPESTATUS is how this driver reads the
    # status the pipe would have swallowed.
    set +e
    "$REAL" 2>&1 | cat >"$OUT"
    RC=${PIPESTATUS[0]}
    set -e
    exits 2
    says "refuses pipes"
    says "The exit status is the verdict"
}

case_an_unknown_option_is_refused() {
    CURRENT="an unknown option is refused"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    set +e
    "$REAL" --force >"$OUT" 2>&1
    RC=$?
    set -e
    exits 2
    says "unknown option"
    # The step banner, spelled with the CURRENT total read out of the script.
    says_not "step 1/${STEP_TOTAL_IN_SCRIPT}"
}

case_no_branch_at_all_is_refused() {
    fresh_source
    run_raw "no branch at all is refused"
    exits 2
    says "needs the rung branch"
    says_not "step 1/${STEP_TOTAL_IN_SCRIPT}"
}

case_a_branch_this_checkout_does_not_have_is_refused() {
    fresh_source
    run_it "a branch this checkout does not have is refused" "rung-that-never-existed"
    exits 2
    says "no local branch 'rung-that-never-existed'"
    if [ -e "$DEST" ]; then
        bad "the destination was created anyway: $DEST"
    else
        ok "nothing was created at the destination"
    fi
}

# THE HAPPY PATH, end to end: clone, a real merge, the derived name, the carry,
# and a clean verdict key.
case_the_happy_path_clones_merges_derives_and_ends_clean() {
    fresh_source
    source_env "ZITADEL_PAT=${CARRY_VALUE}" "ZITADEL_ISSUER=http://localhost:8081"
    local branch_tip main_tip reflog_before reflog_after
    branch_tip="$(git -C "$SRC" rev-parse rung-x)"
    main_tip="$(git -C "$SRC" rev-parse main)"
    # CRITERION 47.5: this instrument never folds main into the SOURCE branch.
    # A `git merge` into `rung-x` here would write a reflog entry, so the
    # source's whole reflog is the witness — taken across the run rather than
    # reasoned about, which is the same standard the seed's read-only assertion
    # holds itself to.
    reflog_before="$(git -C "$SRC" reflog --all 2>/dev/null | digest_stdin)"

    run_it "the happy path clones, merges, derives and ends clean" "rung-x"
    exits 0
    reflog_after="$(git -C "$SRC" reflog --all 2>/dev/null | digest_stdin)"
    is "$reflog_after" "$reflog_before" "the SOURCE's reflog across the run"
    says "== READY"
    says "step 4/${STEP_TOTAL_IN_SCRIPT}"

    if [ -d "${DEST}/.git" ]; then
        ok "the clone exists at ${DEST}"
    else
        bad "no clone at ${DEST}"
        return
    fi

    # THE UNION, asserted as ancestry rather than read off the transcript: both
    # tips are in, which is the whole claim step 2 makes.
    if git -C "$DEST" merge-base --is-ancestor "$branch_tip" HEAD; then
        ok "the rung branch tip is an ancestor of the clone's HEAD"
    else
        bad "the rung branch tip ${branch_tip} is NOT in the clone's history"
    fi
    if git -C "$DEST" merge-base --is-ancestor "$main_tip" HEAD; then
        ok "main's tip is an ancestor of the clone's HEAD — the merge really happened"
    else
        bad "main's tip ${main_tip} is NOT in the clone's history — the union was not built"
    fi
    if [ "$(git -C "$DEST" rev-parse HEAD)" = "$branch_tip" ]; then
        bad "the clone's HEAD is still the bare branch tip — nothing was merged"
    else
        ok "the clone's HEAD is past the bare branch tip"
    fi

    # THE VERDICT KEY, re-measured by this drive rather than believed.
    if [ -z "$(git -C "$DEST" status --porcelain)" ]; then
        ok "\`git status --porcelain\` in the clone is empty"
    else
        bad "the clone is not clean: $(git -C "$DEST" status --porcelain | tr '\n' ' ')"
    fi

    # The .env exists, is not tracked, and carries what was announced.
    if [ -f "${DEST}/.env" ]; then
        ok "the clone has a .env"
    else
        bad "the clone has no .env"
    fi
}

# CRITERION: the clone can be PUSHED FROM, which means its hooks run.
#
# WHAT `git clone` DOES NOT COPY. Committed state, and nothing else: not
# `core.hooksPath` (config is per-repository), not a hook file — `.git/hooks` in
# a fresh clone is populated from the templates and holds `*.sample` and no more.
# A clone is therefore HOOKLESS, and hooklessness is silent in the direction that
# costs: `git push --dry-run` from it exits 0 having consulted nothing, which is
# indistinguishable from a wall that passed the tree.
#
# MEASURED ON 2026-09-18, and this line is the fix's other half. The verifier box
# wrapper vouches for the tree it is about to send by running a `--dry-run`
# through this machine's pre-push hook. From the primary that fired the hook and
# demanded a full gate; from a clone of the same tree it fired NO hook, and the
# box carried a tree no wall had ever seen. `scripts/verifier_box.sh` now refuses
# a vouch whose hook left no sentinel; this sets the config that makes the hook
# run at all.
case_the_clone_carries_the_hooks_path() {
    fresh_source
    run_it "the clone carries the hooks path" "rung-x"
    exits 0

    if [ -d "${DEST}/.git" ]; then
        ok "the clone exists at ${DEST}"
    else
        bad "no clone at ${DEST}"
        return
    fi

    local configured
    configured="$(git -C "$DEST" config --get core.hooksPath || true)"
    if [ "$configured" = "scripts/githooks" ]; then
        ok "the clone's core.hooksPath is scripts/githooks"
    else
        bad "the clone's core.hooksPath is '${configured:-<unset>}' — a clone that cannot run a hook vouches for nothing it pushes"
    fi

    # AND IT IS ANNOUNCED, not done quietly. Every other thing this script
    # derives is printed; a hook setting nobody can see in the transcript is a
    # thing the next verifier will not know to check when a push goes silent.
    says "hooks        core.hooksPath=scripts/githooks"
}

# CRITERION: the derived name is db.sh's, not a second copy of its arithmetic.
case_the_database_name_is_asked_for_and_matches_db_sh() {
    fresh_source
    run_it "the database name is asked for and matches db.sh" "rung-x"
    exits 0

    local printed independent
    printed="$(sed -n 's/^   database     \(djb_.*\)$/\1/p' "$OUT" | head -1)"
    if [ -n "$printed" ]; then
        ok "the run printed a derived name: ${printed}"
    else
        bad "the run printed no derived database name"
        return
    fi

    # THE SHAPE, per the derivation `scripts/db.sh` documents: djb_<branch>_<8
    # hex of the SHA-256 of the checkout's absolute top level>.
    if printf '%s' "$printed" | grep -E '^djb_rung_x_[0-9a-f]{8}$' >/dev/null; then
        ok "the shape is djb_<sanitised-branch>_<8 hex>"
    else
        bad "the shape is not djb_rung_x_<8 hex>: '${printed}'"
    fi

    # THE SEAM. Asked independently, from the clone, with the environment's own
    # DATABASE_NAME emptied exactly as the instrument does. Equality here is
    # what proves the instrument re-implemented nothing.
    independent="$(cd "$DEST" && DATABASE_NAME='' bash -c '. ./scripts/db.sh 2>/dev/null; printf "%s" "${DATABASE_NAME:-}"')"
    if [ "$printed" = "$independent" ]; then
        ok "it equals what the clone's own scripts/db.sh answers"
    else
        bad "the instrument printed '${printed}' where db.sh answers '${independent}'"
    fi

    # It must be the CLONE's name, never the source's — that is the whole
    # reason the derivation is run inside the clone.
    local source_name
    source_name="$(cd "$SRC" && DATABASE_NAME='' bash -c '. ./scripts/db.sh 2>/dev/null; printf "%s" "${DATABASE_NAME:-}"')"
    if [ "$printed" != "$source_name" ]; then
        ok "it is the CLONE's name, not the source checkout's (${source_name})"
    else
        bad "the clone was given the SOURCE checkout's database name — two checkouts, one database"
    fi

    # And it reaches the file a bare `manage.py` reads.
    if grep -qx "DATABASE_NAME=${printed}" "${DEST}/.env"; then
        ok "the clone's .env pins DATABASE_NAME=${printed}"
    else
        bad "the derived name never reached the clone's .env"
    fi
}

# CRITERION: a DATABASE_NAME in the caller's shell must NOT win here.
case_an_exported_database_name_does_not_reach_the_clone() {
    fresh_source
    CURRENT="an exported DATABASE_NAME does not reach the clone"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    DEST="${WORK}/clone${N}"
    UV_LOG="${WORK}/uv${N}.log"
    : >"$UV_LOG"
    RC=0
    # THE SHIM IS ON PATH HERE TOO. This case has its own runner because the
    # thing under test is an EXPORTED variable, but a run without the shim would
    # reach the real `uv` in a repository with no `pyproject.toml` and fail at
    # the python-dependencies step for a reason that has nothing to do with
    # `DATABASE_NAME`. Every full run of the instrument goes through the shim.
    (
        cd "$SRC" || exit 2
        export PATH="${UV_SHIM_DIR}:$PATH"
        export DJB_DRIVE_UV_LOG="$UV_LOG"
        export DJB_DRIVE_UV_RC="$UV_RC"
        DATABASE_NAME=djb_the_callers_own ./scripts/verify_start.sh rung-x "$DEST"
    ) >"$OUT" 2>&1 || RC=$?
    exits 0
    says "is set in this shell and is IGNORED here"
    if grep -q 'DATABASE_NAME=djb_the_callers_own' "${DEST}/.env" 2>/dev/null; then
        bad "the caller's exported name was written into the clone's .env — two checkouts, one database"
    else
        ok "the caller's exported name is not in the clone's .env"
    fi
}

# CRITERION 3: the ZITADEL carry, announced by KEY NAME and never by value.
case_the_zitadel_carry_announces_names_and_never_values() {
    fresh_source
    source_env \
        "ZITADEL_PAT=${CARRY_VALUE}" \
        "ZITADEL_ISSUER=http://localhost:8081" \
        "ZITADEL_ORG_NAME=" \
        "DATABASE_URL=postgres://not-a-zitadel-key/"
    run_it "the zitadel carry announces names and never values" "rung-x"
    exits 0
    says "carried 2 key(s)"
    says "ZITADEL_PAT"
    says "ZITADEL_ISSUER"
    # THE POINT OF THE CASE. The value is in the file and never in the output.
    if grep -qF -- "$CARRY_VALUE" "$OUT"; then
        bad "the carried VALUE was printed — the announcement is by name only"
    else
        ok "the carried value never appears in the output"
    fi
    if grep -qxF "ZITADEL_PAT=${CARRY_VALUE}" "${DEST}/.env"; then
        ok "the value reached the clone's .env"
    else
        bad "the value did not reach the clone's .env — the carry did nothing"
    fi
    # THE CLOSED POPULATION. Nothing but ZITADEL_* moves.
    if grep -q '^DATABASE_URL=postgres://not-a-zitadel-key/' "${DEST}/.env"; then
        bad "a non-ZITADEL line was carried — the population is not closed"
    else
        ok "the non-ZITADEL line was not carried"
    fi
    # An empty key is reported rather than silently dropped.
    says "ZITADEL_ORG_NAME"
}

# The empty-primary negative case: present, blank, nothing carried, said.
case_an_empty_primary_carries_nothing_and_says_so() {
    fresh_source
    source_env "ZITADEL_PAT=" "ZITADEL_ISSUER="
    run_it "an empty primary carries nothing and says so" "rung-x"
    exits 0
    says "nothing carried"
    says "is empty"
    says_not "carried 1 key(s)"
}

case_a_primary_with_no_env_at_all_says_so() {
    fresh_source
    rm -f "${SRC}/.env"
    run_it "a primary with no .env at all says so" "rung-x"
    exits 0
    says "no .env to carry from"
}

# CRITERION 4: the dirty-source refusal.
case_a_dirty_source_checkout_is_refused_and_nothing_is_cloned() {
    fresh_source
    # THE VICTIM IS THIS CASE'S OWN: a modification and an untracked file it
    # made itself, never found state.
    echo "work in progress nobody committed" >>"${SRC}/tracked.txt"
    echo "a new file nobody has added yet" >"${SRC}/untracked-work.txt"
    run_it "a dirty source checkout is refused and nothing is cloned" "rung-x"
    exits 2
    says "uncommitted work"
    says "untracked-work.txt"
    says "tracked.txt"
    says "Nothing was cloned, merged or written."
    if [ -e "$DEST" ]; then
        bad "the destination was created anyway: $DEST"
    else
        ok "nothing was created at the destination"
    fi
    # And the work is still there — a guard that returns the right code over a
    # destroyed tree is not a guard.
    if grep -q "work in progress nobody committed" "${SRC}/tracked.txt" &&
        [ -f "${SRC}/untracked-work.txt" ]; then
        ok "the uncommitted work is untouched"
    else
        bad "the uncommitted work did not survive the refusal"
    fi
}

# The allowance, driven where it is REAL: a source repository that does not
# ignore `*.log` at all, so the log is genuinely untracked and the refusal has
# to decline to fire.
case_an_untracked_log_in_the_source_is_not_dirt() {
    fresh_source "no-gitignore"
    echo "a gate log, exactly where every agent is told to put one" >"${SRC}/gate-somebody.log"
    run_raw "an untracked log in the source is not dirt" "rung-x" "${WORK}/clone-logcase"
    says_not "uncommitted work"
    says "step 1/${STEP_TOTAL_IN_SCRIPT}"
    if [ -d "${WORK}/clone-logcase/.git" ]; then
        ok "the clone was made — the log did not stop it"
    else
        bad "no clone was made; the log was treated as dirt"
    fi
}

# THE TOOTH, from the direction a verifier meets it: the clone finishes clean,
# the verifier writes a scratch note into it, and the guard refuses BY NAME.
case_a_planted_stray_in_the_clone_is_refused_by_name() {
    fresh_source
    run_it "a planted stray in the clone is refused by name" "rung-x"
    exits 0
    local clone="$DEST"

    # THE PLANT. This case's own file, in this case's own clone.
    echo "verification notes the verifier meant to keep" >"${clone}/verifier-notes.md"

    CURRENT="a planted stray in the clone is refused by name"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$SRC" && ./scripts/verify_start.sh --check "$clone") >"$OUT" 2>&1 || RC=$?
    exits 2
    says "STRAY FILES"
    says "verifier-notes.md"
    says "SHIFTS THE KEY"

    # AND THE OTHER DIRECTION: remove the plant, and the same guard goes green.
    # A refusal that cannot be cleared is indistinguishable from a broken one.
    rm -f "${clone}/verifier-notes.md"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$SRC" && ./scripts/verify_start.sh --check "$clone") >"$OUT" 2>&1 || RC=$?
    exits 0
    says "CLEAN"

    # And a log in the same place is the one allowance, proven rather than
    # assumed — this clone's .gitignore does ignore it, so the assertion is
    # that the guard is silent, which it must be either way.
    echo "a gate log" >"${clone}/gate-verification.log"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$SRC" && ./scripts/verify_start.sh --check "$clone") >"$OUT" 2>&1 || RC=$?
    exits 0
}

# THE SAME TOOTH, INLINE, in the run's own step 4 — and the file it names is
# the one the instrument itself wrote. This is `verify_start.sh`'s declared
# blind spot 4 asserted as behaviour.
case_a_repository_that_does_not_ignore_dotenv_is_refused_at_step_4() {
    fresh_source "bare-gitignore"
    run_it "a repository that does not ignore dotenv is refused at step 4" "rung-x"
    exits 2
    says "step ${STEP_TOTAL_IN_SCRIPT}/${STEP_TOTAL_IN_SCRIPT}"
    says "STRAY FILES"
    says ".env"
    # The clone is still there to be read; the refusal is a verdict, not a
    # cleanup.
    if [ -d "${DEST}/.git" ]; then
        ok "the clone is left in place for the reader"
    else
        bad "the clone was removed — there is nothing left to diagnose"
    fi
}

case_an_occupied_destination_is_refused() {
    fresh_source
    N=$((N + 1))
    local occupied="${WORK}/occupied${N}"
    drive_require_scratch occupied "${occupied:-}"
    mkdir -p "$occupied"
    echo "somebody else's half-finished verification" >"${occupied}/in-progress.txt"
    run_raw "an occupied destination is refused" "rung-x" "$occupied"
    exits 2
    says "the destination is not empty"
    if [ -f "${occupied}/in-progress.txt" ]; then
        ok "what was there is still there"
    else
        bad "the occupied destination was clobbered"
    fi
}

case_a_conflicting_rung_branch_is_an_exit_1_naming_the_paths() {
    fresh_source
    # Both sides touch the same line of the same file. `fresh_source` already
    # moved main; this moves the rung branch onto the same file.
    git -C "$SRC" checkout -q rung-x
    echo "the rung's own second line" >>"${SRC}/tracked.txt"
    git -C "$SRC" add tracked.txt
    git -C "$SRC" commit -q -m "the rung touches tracked.txt too"
    git -C "$SRC" checkout -q main
    run_it "a conflicting rung branch is an exit 1 naming the paths" "rung-x"
    # 1, not 2: the merge RAN and came back with a real answer.
    exits 1
    says "CONFLICT"
    says "tracked.txt"
    says "left AT THE CONFLICT"
}

# CRITERION 1's other half, read as CODE. The header explains at length why
# this file is never read into a shell, and a grep that cannot tell the
# explanation from the act would make the explanation unwritable — the known
# class where prose spelling a censused thing is counted as the thing. So
# comments are stripped first, and what is left is the executable text.
case_it_never_reads_the_environment_file_into_its_own_shell() {
    CURRENT="it never reads the environment file into its own shell"
    local code="${WORK}/verify_start.code"
    sed 's/#.*//' "$REAL" >"$code"
    OUT="$code"
    if grep -qE '(^|[^a-zA-Z_])(source|\.)[[:space:]]+[^[:space:]]*\.env([^a-zA-Z]|$)' "$code"; then
        bad "the executable text sources the environment file — the one thing this instrument must not do"
        grep -nE '(^|[^a-zA-Z_])(source|\.)[[:space:]]+[^[:space:]]*\.env([^a-zA-Z]|$)' "$code" | sed 's/^/             | /'
    else
        ok "no sourcing of the environment file anywhere in the executable text"
    fi
    # It DOES source db.sh — inside the clone, in a subshell. That is the seam,
    # and losing it would mean the arithmetic came back as a second copy.
    if grep -q 'db\.sh' "$code"; then
        ok "it still consumes scripts/db.sh as the derivation seam"
    else
        bad "it no longer names scripts/db.sh — the derivation has gone somewhere else"
    fi
    # A second copy of the path-hash arithmetic is the thing the seam exists to
    # prevent. Code only, comments already stripped.
    # `sha256_of` JOINS THE PATTERN. The gate family grew one helper for the
    # two spellings of SHA-256 (scripts/gate_refuse.sh), and a pattern that
    # only knew the tool names would wave a second copy through the moment it
    # was written as a call to that helper instead.
    if grep -qE 'shasum|sha256sum|sha256_of|openssl dgst|cksum' "$code"; then
        bad "it has grown its own path-hash arithmetic — that is the second copy db.sh exists to avoid"
    else
        ok "it hashes nothing itself; db.sh's answer is the name"
    fi
    # And the header really does record the cost, which is criterion 1's
    # parenthesis. This one looks at the COMMENTS on purpose.
    if grep -q 'three gate runs\|THREE GATE RUNS' "$REAL"; then
        ok "the header records what sourcing that file cost a sibling product"
    else
        bad "the header no longer records the cost — the rule is back to being an assertion"
    fi
    OUT=""
}

# --- the local main ref the clone is given ------------------------------------
#
# THE PAIRING, and it is owed rather than optional. Every changed-file
# derivation in this repository forks from the LOCAL `refs/heads/main`, and
# `git clone --branch <rung>` leaves a clone with exactly one local head — the
# rung's. `scripts/loop_tier.sh` REFUSES that shape outright rather than
# grading a rung against a thin basis, so without this line the house's own
# verification tool would be the first thing to trip the house's own refusal.
#
# RED-FIRST IN THE CASE ITSELF: the first half makes the clone `git clone`
# would have made and shows the ref is absent; the second half runs the real
# script and shows it there, at the sha the script already verified. A case
# that only asserted the second half could not tell "the script creates it"
# from "clone gives it to you anyway".
case_the_clone_is_given_a_local_main_ref_at_the_verified_sha() {
    fresh_source
    CURRENT="the clone is given a local refs/heads/main"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0

    # (a) the shape `git clone --branch` leaves, made here so the red is this
    #     case's own and not an assertion about somebody's memory of git.
    local plain="${WORK}/plainclone${N}"
    git clone --quiet --branch rung-x "$SRC" "$plain" >"$OUT" 2>&1
    if git -C "$plain" rev-parse -q --verify refs/heads/main >/dev/null 2>&1; then
        bad "a plain --branch clone already carries refs/heads/main — the premise is wrong"
    else
        ok "RED: a plain --branch clone carries NO refs/heads/main"
    fi

    # (b) the real script, on the same source.
    run_it "the clone is given a local refs/heads/main" "rung-x"
    exits 0
    says "main ref"
    local want got
    want=$(git -C "$SRC" rev-parse refs/heads/main)
    if got=$(git -C "$DEST" rev-parse -q --verify refs/heads/main 2>/dev/null); then
        ok "the clone carries refs/heads/main"
        is "$got" "$want" "the ref's sha (the verified MAIN_SHA)"
    else
        bad "the clone still has no refs/heads/main"
    fi
}

# THE FOLD POINT IS RECORDED IN THE CLONE, as `refs/djb/base`. It was printed
# and never written, so a clone whose union was pushed to a box as `main` — or
# committed as its own `main` — carried no fork point: `merge-base HEAD main` is
# HEAD there and the box's `--loop` measured an empty scope. The push reads this
# ref (scripts/verifier_box.sh, cmd_push). Both arms: a real merge (the fold
# point is the branch point) and an already-folded branch (it is main's tip).
case_the_clone_records_its_fold_point_as_refs_djb_base() {
    local want got arm
    for arm in moved-on already-up-to-date; do
        fresh_source "ignores-dotenv" "$arm"
        want=$(git -C "$SRC" merge-base main rung-x)
        run_it "the clone records its fold point as refs/djb/base (${arm})" "rung-x"
        exits 0
        if got=$(git -C "$DEST" rev-parse -q --verify refs/djb/base 2>/dev/null); then
            ok "the clone carries refs/djb/base"
            is "$got" "$want" "refs/djb/base (the fold point, ${arm})"
        else
            bad "the clone carries no refs/djb/base — the fold point was printed and not recorded"
        fi
        says "fork point   refs/djb/base = $(git -C "$SRC" rev-parse --short "$want")"
        says "fold point   ${want}"
        # THE CLONE'S OWN, NEVER THE SOURCE'S — a ref written into the source
        # would be every linked worktree's of that family.
        if git -C "$SRC" rev-parse -q --verify refs/djb/base >/dev/null 2>&1; then
            bad "refs/djb/base was written into the SOURCE checkout"
        else
            ok "the source checkout carries no refs/djb/base"
        fi
    done
}

# --- the loop-verdict seed ----------------------------------------------------
#
# The scratch source can carry a `.git/djb-loop-verdicts` with rows of both
# shapes, which is the whole of what the COUNTING cases need.
#
# THE LIVE HIT IS NOW HERE, and the sentence that used to stand on this line —
# that it could not be, because the key's environment fingerprint censuses
# `.venv/**/*.dist-info` and this scratch repository has none — is false from
# the commit that gave the instrument a python-dependencies step. What made it
# true was the absence the step closes: the `uv` shim writes the `.dist-info`
# directories the census counts, so `loop_env_fingerprint` answers in the clone
# and `case_a_seeded_row_is_a_hit_once_the_venv_exists` derives a real key in
# one clone and looks it up in the next. What is still NOT claimed here is a
# hit against a REAL builder's ledger row; that is the verifier's own first
# `--loop` in a real clone, and its `loop:` row is where it shows up.

# A well-formed loop row, and a malformed one, written into the source's ledger.
seed_source_ledger() {
    local good=${1:-2} bad_rows=${2:-1} i common
    common=$(git -C "$SRC" rev-parse --git-common-dir)
    case "$common" in
    /*) ;;
    *) common="${SRC}/${common}" ;;
    esac
    : >"${common}/djb-loop-verdicts"
    i=0
    while [ "$i" -lt "$good" ]; do
        printf 'loop-v1 loop-v1:%064d loop 2026-09-07T00:00:0%sZ caller=drive scope=mode=fast_own=x_scope=x_always=d passes=1 tree=%064d env=%064d\n' \
            "$i" "$i" "$i" "$i" >>"${common}/djb-loop-verdicts"
        i=$((i + 1))
    done
    i=0
    while [ "$i" -lt "$bad_rows" ]; do
        printf 'not-a-loop-row whatever it says here\n' >>"${common}/djb-loop-verdicts"
        i=$((i + 1))
    done
    printf '%s\n' "${common}/djb-loop-verdicts"
}

case_the_loop_ledger_is_seeded_and_the_counts_are_exact() {
    fresh_source
    local ledger
    ledger=$(seed_source_ledger 3 2)
    run_it "the loop ledger is seeded and the counts are exact" "rung-x"
    exits 0
    says "ledger seeded: 3 loop rows"
    says "(2 skipped: not loop-v1)"
    if [ -f "${DEST}/.git/djb-loop-verdicts" ]; then
        ok "the clone carries a seeded ledger"
        is "$(grep -c '^loop-v1 ' "${DEST}/.git/djb-loop-verdicts")" "3" "the rows that landed"
        if grep -F "not-a-loop-row" "${DEST}/.git/djb-loop-verdicts" >/dev/null; then
            bad "a malformed line was copied through"
        else
            ok "the malformed lines were skipped, not copied"
        fi
    else
        bad "no ledger in the clone at ${DEST}/.git/djb-loop-verdicts"
    fi
    # The seed note, which is what lets the gate's banner say how many rows in
    # its ledger it did not measure itself.
    if [ -f "${DEST}/.git/djb-loop-verdicts-seed" ]; then
        ok "the seed note is beside the ledger"
        # THE SUFFIX, NOT THE ABSOLUTE PATH. On macOS the scratch directory is
        # reached through /var -> /private/var, and the script resolves its own
        # root while this drive does not — two spellings of one file, and an
        # equality assertion on them fails for a reason that has nothing to do
        # with the seed. What is asserted is that the note names A loop ledger
        # and that the file it names IS this source's, by content.
        says "/.git/djb-loop-verdicts"
        local named
        named=$(sed -n 's/^.*from=\(.*\)$/\1/p' "${DEST}/.git/djb-loop-verdicts-seed" | tail -1)
        if [ -f "$named" ] && cmp -s "$named" "$ledger"; then
            ok "the file the note names is this source's ledger, byte for byte"
        else
            bad "the note names '${named}', which is not this source's ledger"
        fi
        if grep -F "seeded=3" "${DEST}/.git/djb-loop-verdicts-seed" >/dev/null; then
            ok "the note records the seeded count"
        else
            bad "the note does not record seeded=3"
        fi
    else
        bad "no seed note beside the seeded ledger"
    fi
}

case_a_source_with_no_loop_ledger_is_a_named_absence() {
    fresh_source
    run_it "a source with no loop ledger is a named absence" "rung-x"
    exits 0
    says "ledger not seeded:"
    says "has no loop ledger"
    if [ -f "${DEST}/.git/djb-loop-verdicts" ]; then
        bad "a ledger was created from nothing"
    else
        ok "no ledger was invented"
    fi
}

case_the_seed_never_writes_to_the_source() {
    fresh_source
    local ledger before after
    ledger=$(seed_source_ledger 2 1)
    before=$(digest_stdin <"$ledger")
    run_it "the seed never writes to the source" "rung-x"
    exits 0
    after=$(digest_stdin <"$ledger")
    is "$after" "$before" "the SOURCE ledger's sha across the clone"

    # And the other direction: a row planted in the CLONE stays in the clone.
    printf 'loop-v1 loop-v1:%064d loop 2026-09-07T00:00:09Z caller=planted scope=x passes=1 tree=x env=x\n' 9 \
        >>"${DEST}/.git/djb-loop-verdicts"
    is "$(digest_stdin <"$ledger")" "$before" \
        "the SOURCE ledger's sha after a row is planted in the clone"
}

case_step_four_is_still_green_over_the_seeded_file() {
    fresh_source
    seed_source_ledger 2 0 >/dev/null
    run_it "step four is still green over the seeded file" "rung-x"
    exits 0
    # The guard ran and found nothing: the seeded file is inside `.git/`, which
    # `git status` does not report. Asserted, because "it is in .git so it is
    # fine" is exactly the kind of thing that stops being true quietly.
    says "clean"
    says "READY"
    local strays
    strays=$(git -C "$DEST" status --porcelain)
    if [ -z "$strays" ]; then
        ok "git status in the clone is empty — the seed is invisible to it"
    else
        bad "the seed made the clone dirty: ${strays}"
    fi
}

# --- the python-dependencies step ---------------------------------------------
#
# THE MEASURED DEFECT THESE CLOSE, from a field test on 2026-09-12: the seed above copied
# 51 rows into a clone that had no `.venv`, the consult censused `.venv`, found
# nothing, refused to derive a key at all, and measured the whole suite in full
# (201 s). Every one of those rows was dead on arrival. The seed and the consult
# were looking at two environments; these cases are how they are one.

# THE ORDER IS THE PROPERTY, not the presence. A sync that ran AFTER the seed
# would leave the seed written over an environment that did not exist yet, which
# is the defect with an extra step in it — so the transcript's line positions
# are compared rather than a pair of "it happened" assertions.
case_the_venv_is_provisioned_before_the_seed_and_the_order_is_asserted() {
    fresh_source
    run_it "the venv is provisioned before the seed, and the order is asserted" "rung-x"
    exits 0
    says "python dependencies"
    says "uv sync --frozen"

    # (a) THE SHIM'S LOG: the sync really was asked for, with --frozen.
    if grep -qF -- "sync --frozen" "$UV_LOG"; then
        ok "the uv shim was invoked as \`sync --frozen\`"
    else
        bad "the uv shim's log does not carry \`sync --frozen\`: $(tr '\n' '|' <"$UV_LOG")"
    fi

    # (b) THE TRANSCRIPT'S LINE POSITIONS: union merge < sync < seed.
    local merge_ln sync_ln seed_ln
    # `|| true` on each: under `set -euo pipefail` a grep that matches nothing
    # kills the whole drive, and "the banner is missing" is a FAILED ASSERTION
    # here, never a dead driver.
    merge_ln=$(grep -nF -- '· union merge' "$OUT" | head -1 | cut -d: -f1) || true
    sync_ln=$(grep -nF -- 'uv-shim invoked: sync --frozen' "$OUT" | head -1 | cut -d: -f1) || true
    seed_ln=$(grep -nF -- '· loop-verdict seed' "$OUT" | head -1 | cut -d: -f1) || true
    if [ -n "$merge_ln" ] && [ -n "$sync_ln" ] && [ -n "$seed_ln" ]; then
        if [ "$merge_ln" -lt "$sync_ln" ] && [ "$sync_ln" -lt "$seed_ln" ]; then
            ok "the order in the transcript is union merge (${merge_ln}) < sync (${sync_ln}) < seed (${seed_ln})"
        else
            bad "out of order: union merge ${merge_ln}, sync ${sync_ln}, seed ${seed_ln}"
        fi
    else
        bad "a banner is missing: union merge '${merge_ln}', sync '${sync_ln}', seed '${seed_ln}'"
    fi

    # (c) AND THE THING THE CENSUS ACTUALLY COUNTS is in the clone. Not "a
    #     directory exists" — the `*.dist-info` directories `loop_env_fingerprint`
    #     reaches with `find -maxdepth 4`.
    local dists
    dists=$(find "${DEST}/.venv" -maxdepth 4 -type d -name '*.dist-info' 2>/dev/null | wc -l | tr -d ' ') || dists=0
    if [ "${dists:-0}" -gt 0 ]; then
        ok "the clone's .venv carries ${dists} dist-info directories the census can count"
    else
        bad "the clone's .venv has nothing the loop ledger's census would find"
    fi

    # (d) The step says the fingerprint it derived, so a reader can compare it
    #     with the one the miss banner prints.
    says "fingerprint  "
}

case_no_sync_skips_the_step_and_says_the_seed_cannot_hit() {
    fresh_source
    seed_source_ledger 2 0 >/dev/null
    run_it "--no-sync skips the step and says the seed cannot hit" "rung-x" "--no-sync"
    exits 0
    says "SKIPPED"
    says "THE SEED BELOW CANNOT HIT"
    says "re-measure the suite in full"
    # The seed still runs — the skip costs the HIT, not the rows.
    says "ledger seeded: 2 loop rows"
    if [ -s "$UV_LOG" ]; then
        bad "uv was invoked anyway: $(tr '\n' '|' <"$UV_LOG")"
    else
        ok "uv was never invoked"
    fi
    if [ -e "${DEST}/.venv" ]; then
        bad "a venv was made anyway at ${DEST}/.venv"
    else
        ok "the clone has no .venv"
    fi
    # And the honest half: with no venv the ledger CANNOT answer, which is the
    # exact refusal the field test measured.
    local fp
    fp=$(cd "$DEST" && . ./scripts/gate_ledger.sh >/dev/null 2>&1 && loop_env_fingerprint 2>/dev/null) || fp=""
    if [ -z "$fp" ]; then
        ok "loop_env_fingerprint refuses in the skipped clone — env= unstated, as the skip says"
    else
        bad "the skipped clone somehow fingerprints: ${fp}"
    fi
    # AND THE PREDICTION SAYS THE SAME THING IN ITS OWN GRAMMAR. A clone with no
    # venv derives no key at all, so no tree comparison could make it a hit —
    # predicting one here would be the line claiming something it cannot know.
    says "consult: WILL RUN (--no-sync"
    says_not "EXPECTED HIT"
}

# A FAILING SYNC IS COULD-NOT-LOOK, AND NOTHING IS SEEDED. The clone is not
# ready; a seed written over it would be rows nothing can ever match, which is
# the measured defect with the extra insult of a green exit.
case_a_failing_sync_is_could_not_look_and_seeds_nothing() {
    fresh_source
    seed_source_ledger 3 0 >/dev/null
    UV_RC=1
    run_it "a failing sync is could-not-look and seeds nothing" "rung-x"
    UV_RC=0
    exits 2
    says "could not be VERIFIED"
    says "uv sync --frozen"
    says "Nothing was seeded."
    if [ -e "${DEST}/.git/djb-loop-verdicts" ]; then
        bad "the seed ran anyway over a clone with no environment"
    else
        ok "the seed file is absent — nothing was seeded"
    fi
    # The clone is left in place to be read, as every could-not-verify here is.
    if [ -d "${DEST}/.git" ]; then
        ok "the clone is left in place for the reader"
    else
        bad "the clone was removed — there is nothing left to diagnose"
    fi
}

# THE WHOLE POINT OF THE STEP, END TO END, and it is two clones on purpose: the key
# is derived in the FIRST by the clone's own `gate_ledger.sh`, the row is written
# into the SOURCE's ledger at that key the way a builder's `--loop` would have
# banked it, and the SECOND clone is where the lookup has to hit. The union is
# the branch tip (`already-up-to-date`), which is the one shape the instrument's
# blind spot 6 says a seeded row can hit in at all.
case_a_seeded_row_is_a_hit_once_the_venv_exists() {
    fresh_source "ignores-dotenv" "already-up-to-date"
    local scope="mode=loop_own=x_scope=x_always=d"
    local fp key tree clone_a clone_b key_b row ledger common

    run_it "a seeded row is a hit once the venv exists (phase A: derive)" "rung-x"
    exits 0
    says "already up to date"
    clone_a="$DEST"

    fp=$(cd "$clone_a" && . ./scripts/gate_ledger.sh >/dev/null 2>&1 &&
        loop_env_fingerprint 2>/dev/null) || fp=""
    if [ -n "$fp" ]; then
        ok "the clone's own gate_ledger.sh derives an env fingerprint: ${fp}"
    else
        bad "env= unstated — the clone's gate_ledger.sh could not census .venv"
        return
    fi

    tree=$(git -C "$clone_a" rev-parse 'HEAD^{tree}') || tree=""
    key=$(cd "$clone_a" && . ./scripts/gate_ledger.sh >/dev/null 2>&1 &&
        loop_ledger_key "$tree" "$scope" 2>/dev/null) || key=""
    if [ -n "$key" ]; then
        ok "a loop key is derivable in the clone: ${key}"
    else
        bad "no loop key could be derived in the clone"
        return
    fi

    # THE BUILDER'S ROW, at that key, in the SOURCE's ledger.
    ledger=$(seed_source_ledger 1 0)
    printf 'loop-v1 %s loop 2026-09-14T00:00:00Z caller=builder scope=%s passes=1 tree=%s env=%s\n' \
        "$key" "$scope" "$tree" "$fp" >>"$ledger"

    run_it "a seeded row is a hit once the venv exists (phase B: consult)" "rung-x"
    exits 0
    says "ledger seeded: 2 loop rows"
    clone_b="$DEST"

    key_b=$(cd "$clone_b" && . ./scripts/gate_ledger.sh >/dev/null 2>&1 &&
        loop_ledger_key "$(git rev-parse 'HEAD^{tree}')" "$scope" 2>/dev/null) || key_b=""
    is "$key_b" "$key" "the key the SECOND clone derives"

    row=$(cd "$clone_b" && . ./scripts/gate_ledger.sh >/dev/null 2>&1 &&
        loop_ledger_lookup "$key_b" 2>/dev/null) || row=""
    if [ -n "$row" ]; then
        ok "HIT — the lookup returns the seeded row: ${row}"
    else
        bad "miss(unmatched) — the seeded row is still dead on arrival"
    fi

    # AND THE CONTROL, so the hit is not an artefact of a lookup that matches
    # anything: the same lookup at a key nothing seeded must miss.
    common=$(printf 'loop-v1:%064d' 7)
    row=$(cd "$clone_b" && . ./scripts/gate_ledger.sh >/dev/null 2>&1 &&
        loop_ledger_lookup "$common" 2>/dev/null) || row=""
    if [ -z "$row" ]; then
        ok "a key nothing seeded still misses — the lookup is not matching anything"
    else
        bad "the lookup answered for a key nothing seeded: ${row}"
    fi
}

# THE VERDICT KEY IS UNCHANGED BY THE NEW STEP, which is the one way this step
# could have broken the guard the whole script exists to run: `.venv` is ignored
# in this template and in every product cloned from it, so the tree the last step
# measures is the tree it measured before.
case_the_verdict_key_ignores_the_provisioned_venv() {
    fresh_source
    run_it "the verdict key ignores the provisioned venv" "rung-x"
    exits 0
    says "clean"
    says "READY"
    if [ -d "${DEST}/.venv" ]; then
        ok "the clone really does have a .venv to be ignored"
    else
        bad "no .venv in the clone — this case would pass vacuously"
        return
    fi
    local strays
    strays=$(git -C "$DEST" status --porcelain) || strays="git status itself failed"
    if [ -z "$strays" ]; then
        ok "git status in the clone is empty — the venv shifts no verdict key"
    else
        bad "the venv made the clone dirty: ${strays}"
    fi
    if git -C "$DEST" check-ignore -q .venv; then
        ok "the clone's own .gitignore is what ignores it"
    else
        bad "git does not consider .venv ignored in the clone"
    fi
}

# --- docs dirt in the source is announced, not refused ------------------------

case_docs_only_dirt_in_the_source_is_announced_and_the_clone_proceeds() {
    fresh_source
    mkdir -p "${SRC}/docs/product"
    echo "a committed plan" >"${SRC}/docs/product/queue.md"
    git -C "$SRC" add docs/product/queue.md
    git -C "$SRC" commit -q -m "the plan"
    # THE VICTIM IS THIS CASE'S OWN: one modified tracked docs file and one
    # untracked docs file, both under docs/product/.
    echo "an uncommitted ledger row" >>"${SRC}/docs/product/queue.md"
    echo "an unsaved cycle file" >"${SRC}/docs/product/in-flight.md"
    run_it "docs-only dirt is announced and the clone proceeds" "rung-x"
    exits 0
    says "path(s) under docs/product/ are dirty here and are NOT in"
    says "a criterion read from an uncommitted plan is not in"
    says "docs/product/queue.md"
    says "docs/product/in-flight.md"
    says "READY"
    # The clone is from HEAD: the uncommitted line is not in it.
    if grep -F "an uncommitted ledger row" "${DEST}/docs/product/queue.md" >/dev/null 2>&1; then
        bad "the clone somehow carries the uncommitted line"
    else
        ok "the clone is from HEAD — the uncommitted line is not in it"
    fi
    if [ -f "${DEST}/docs/product/in-flight.md" ]; then
        bad "the clone carries the untracked file"
    else
        ok "the clone does not carry the untracked docs file"
    fi
    # And the source is untouched.
    if grep -F "an uncommitted ledger row" "${SRC}/docs/product/queue.md" >/dev/null; then
        ok "the source's uncommitted work is untouched"
    else
        bad "the source's uncommitted work did not survive"
    fi
}

case_docs_dirt_mixed_with_code_dirt_is_still_refused_naming_both() {
    fresh_source
    mkdir -p "${SRC}/docs/product"
    echo "a committed plan" >"${SRC}/docs/product/queue.md"
    git -C "$SRC" add docs/product/queue.md
    git -C "$SRC" commit -q -m "the plan"
    echo "an uncommitted ledger row" >>"${SRC}/docs/product/queue.md"
    echo "and a real code change" >>"${SRC}/tracked.txt"
    run_it "docs dirt mixed with code dirt is still refused" "rung-x"
    exits 2
    says "uncommitted work"
    says "docs/product/queue.md"
    says "tracked.txt"
    says "Nothing was cloned, merged or written."
    if [ -e "$DEST" ]; then
        bad "the destination was created anyway: $DEST"
    else
        ok "nothing was created at the destination"
    fi
}

case_the_narrowing_does_not_reach_the_verdict_key_guard() {
    # THE SCOPE OF THE NARROWING, pinned. `strays_in` is shared with step 4 and with
    # `--check`, where a stray docs file in a CLONE is a real finding: something
    # wrote into a tree that had no business being written to. If the narrowing
    # ever migrates into `strays_in`, this case reds.
    fresh_source
    # `docs/product/` has to EXIST in the clone, or git reports the whole
    # untracked directory as `?? docs/` and the case would assert a path git
    # never prints — a case failing for its own set-up rather than its subject.
    mkdir -p "${SRC}/docs/product"
    echo "a committed plan" >"${SRC}/docs/product/queue.md"
    git -C "$SRC" add docs/product/queue.md
    git -C "$SRC" commit -q -m "the plan"
    run_it "the narrowing does not reach the verdict-key guard" "rung-x"
    exits 0
    # THE PLANTED PATH IS ASSEMBLED, NEVER SPELLED. This drive SHIPS (bucket
    # R3) and `publish.sh`'s `dangling-docs` leg reads every `docs/**.md`
    # string in the artifact as a POINTER — so a scratch fixture spelled in
    # full is a pointer at a file the published tree has never had. Same idiom
    # and same reason as `scripts/archaeology_lib.sh`'s assembled bucket globs:
    # name it in halves no pattern can join.
    local planted="product/stray.md"
    echo "written into the clone by something" >"${DEST}/docs/${planted}"
    CURRENT="the narrowing does not reach the verdict-key guard"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$SRC" && ./scripts/verify_start.sh --check "$DEST") >"$OUT" 2>&1 || RC=$?
    exits 2
    says "STRAY FILES"
    says "docs/${planted}"
}

# --- the consult prediction ---------------------------------------------------
#
# WHAT THESE ASSERT, AND THE HALF THEY DO NOT REACH — stated here rather than
# left for a reader to discover, because a drive that is silent about its reach
# is a drive whose green means less than it looks.
#
# The prediction is about ONE half of the loop's verdict key — the TREE — and
# these cases drive exactly that half, plus the two worlds that distinguish it:
# a rung branch that carries main's tip (the builder folded, so step 2 takes its
# *already up to date* arm) and one that does not.
#
# THE LOOP'S OWN BANNER IS NOT PRINTED HERE, and it cannot be: a scratch source
# repository carries four scripts, no Django, no pytest and no `check.sh`, so
# `./scripts/check.sh --loop` has nothing to run in a clone of one. What IS
# driven is THE SEAM THAT BANNER PRINTS FROM — `gate_measured_tree`,
# `loop_ledger_key` and `loop_ledger_lookup`, in the clone, which are the three
# calls `scripts/check.sh` makes at :1720, :1735 and :1738 and the whole of what
# decides a hit from a miss. A prediction the loop's consult contradicts reds
# here. The banner's WORDING is the declared blind spot, and it is the
# verifier's to read in a real clone.

# The clone's measured tree, derived the way the loop derives it: by asking the
# clone's own `scripts/gate_ledger.sh`, never by re-implementing `git add -A`.
clone_measured_tree() {
    (cd "$1" && . ./scripts/gate_ledger.sh >/dev/null 2>&1 && gate_measured_tree 2>/dev/null) || true
}

# The loop's consult in the clone: `hit <key>` or `miss <token>` — the pair
# `scripts/check.sh` turns into its REUSED banner or its `miss(...)` banner.
loop_seam_verdict() {
    (
        cd "$1" || exit 2
        . ./scripts/gate_ledger.sh >/dev/null 2>&1 || exit 2
        seam_tree=$(gate_measured_tree) || {
            echo "miss no-tree"
            exit 0
        }
        # PLAINLY, NOT IN A SUBSTITUTION — `check.sh:1734`'s own note: the
        # globals a fingerprint sets in a subshell die with it, and the
        # attributor below reads one of them.
        loop_env_fingerprint >/dev/null 2>&1 || true
        seam_key=$(loop_ledger_key "$seam_tree" "$2") || {
            echo "miss no-key"
            exit 0
        }
        if loop_ledger_lookup "$seam_key" >/dev/null; then
            printf 'hit %s\n' "$seam_key"
        else
            printf 'miss %s\n' \
                "$(loop_ledger_attribute "$seam_tree" "${LOOP_ENV_FINGERPRINT:-unstated}" "$2" | sed -n '1p')"
        fi
    ) || true
}

# A builder's banked row, written into the SOURCE's ledger at the key THIS clone
# derives — the shape `case_a_seeded_row_is_a_hit_once_the_venv_exists` already
# uses, asked for rather than re-spelled. The key lands on stdout.
#
# IT CARRIES THE COMPONENTS, AND THAT IS NOT DECORATION — it is the difference
# between driving the attributor and driving a fixture artifact. A REAL banked
# row is written by `loop_ledger_record`, which appends
# `env-file= excluded= dists= env-reads= head= merge-base=` after `env=` from
# the global `LOOP_ENV_COMPONENTS`; `loop_ledger_attribute`'s component pass
# RANKS candidate rows by those fields and falls back to a three-line match
# only for rows written before they existed. A planted row without them is
# exactly that pre-components population, so the attributor could not rank it
# and answered `unmatched` where a real row answers `tree` — a green case
# codifying the fixture's own shortcut. A verification against a real banked
# row measured the real token and sent it back; the components are asked for the
# way every other derivation in this drive is, by calling the clone's own
# `loop_env_fingerprint` and reading the global it sets.
plant_builder_row() {
    local clone="$1" scope="$2" ledger="$3" tree fp key derived components
    tree=$(clone_measured_tree "$clone")
    [ -n "$tree" ] || return 1
    # PLAINLY INSIDE THE SUBSHELL, THEN PRINTED — `check.sh:1722-1733`'s own
    # note: the globals `loop_env_fingerprint` sets die with the subshell that
    # called it, so the components have to be printed out of the same shell
    # that derived the digest or the two could disagree.
    derived=$(cd "$clone" && . ./scripts/gate_ledger.sh >/dev/null 2>&1 &&
        loop_env_fingerprint >/dev/null 2>&1 &&
        printf '%s\n%s\n' "$LOOP_ENV_FINGERPRINT" "$LOOP_ENV_COMPONENTS") || derived=""
    fp="${derived%%$'\n'*}"
    components="${derived#*$'\n'}"
    components="${components%$'\n'}"
    [ -n "$fp" ] || return 1
    [ -n "$components" ] || return 1
    key=$(cd "$clone" && . ./scripts/gate_ledger.sh >/dev/null 2>&1 &&
        loop_ledger_key "$tree" "$scope" 2>/dev/null) || key=""
    [ -n "$key" ] || return 1
    printf 'loop-v1 %s loop 2026-09-18T00:00:00Z caller=builder scope=%s passes=1 tree=%s env=%s %s\n' \
        "$key" "$scope" "$tree" "$fp" "$components" >>"$ledger"
    printf '%s\n' "$key"
}

CONSULT_SCOPE="mode=loop_own=x_scope=x_always=d"

# CRITERION 47.2 (a): the folded world predicts a hit, and names the row it
# predicts from.
case_a_folded_branch_predicts_a_hit() {
    fresh_source "ignores-dotenv" "already-up-to-date"
    local ledger key tree

    run_it "a folded branch predicts a hit (phase A: derive)" "rung-x"
    exits 0
    says "already up to date"
    tree=$(clone_measured_tree "$DEST")
    if [ -z "$tree" ]; then
        bad "the clone's own gate_ledger.sh could not measure its tree"
        return
    fi
    ledger=$(seed_source_ledger 1 0)
    key=$(plant_builder_row "$DEST" "$CONSULT_SCOPE" "$ledger") || key=""
    if [ -z "$key" ]; then
        bad "could not plant a builder row at this clone's key"
        return
    fi

    run_it "a folded branch predicts a hit (phase B: predict)" "rung-x"
    exits 0
    says "consult: EXPECTED HIT ${key}"
    says "(union = branch tip; seeded row tree=${tree})"
    says_not "WILL RUN"
    # THE FOLD POINT IS PRINTED IN BOTH ARMS, because 47.1's instrument is a
    # comparison of two shas and the verifier cannot make it without this one.
    says "fold point   $(git -C "$SRC" rev-parse main)"
}

# CRITERION 47.2 (b): main moved after the fold — a run, and the count.
case_main_moved_after_the_fold_predicts_a_run_and_counts() {
    fresh_source "ignores-dotenv" "already-up-to-date"
    local ledger key fold

    run_it "main moved after the fold (phase A: the fold's own clone)" "rung-x"
    exits 0
    ledger=$(seed_source_ledger 1 0)
    key=$(plant_builder_row "$DEST" "$CONSULT_SCOPE" "$ledger") || key=""
    if [ -z "$key" ]; then
        bad "could not plant a builder row at the folded clone's key"
        return
    fi

    # THE WORLD THE CRITERION NAMES: one commit on main after the builder folded.
    fold=$(git -C "$SRC" rev-parse main)
    echo "after the fold" >>"${SRC}/tracked.txt"
    git -C "$SRC" add tracked.txt
    git -C "$SRC" commit -q -m "main moved after the fold"

    run_it "main moved after the fold predicts a run and counts" "rung-x"
    exits 0
    says "consult: WILL RUN (union differs: 1 commit(s) on main since the fold ${fold})"
    says_not "EXPECTED HIT"

    # AND A BRANCH THAT NEVER FOLDED AT ALL — the same arm, a bigger count, so a
    # hard-coded `1` could not pass this case.
    fresh_source
    echo "and again" >>"${SRC}/tracked.txt"
    git -C "$SRC" add tracked.txt
    git -C "$SRC" commit -q -m "main moved a second time"
    fold=$(git -C "$SRC" merge-base main rung-x)
    run_it "a branch that never folded predicts a run and counts" "rung-x"
    exits 0
    says "consult: WILL RUN (union differs: 2 commit(s) on main since the fold ${fold})"
}

# CRITERION 47.2 (c): the tree is right and there is still no row — a NAMED
# absence, never silence and never a hit.
case_no_seeded_row_is_a_named_absence() {
    fresh_source "ignores-dotenv" "already-up-to-date"
    local tree

    # Rows exist — at trees this clone does not have. "No row for THIS tree" is
    # a different sentence from "no ledger", and both are driven.
    seed_source_ledger 2 1 >/dev/null
    run_it "no seeded row is a named absence" "rung-x"
    exits 0
    tree=$(clone_measured_tree "$DEST")
    if [ -z "$tree" ]; then
        bad "the clone's own gate_ledger.sh could not measure its tree"
        return
    fi
    says "consult: WILL RUN (no seeded row for tree ${tree})"
    says_not "EXPECTED HIT"

    # And with no ledger at all in the source, the same sentence — the absence
    # is about the ROW, which is what the next run will look up.
    fresh_source "ignores-dotenv" "already-up-to-date"
    run_it "no ledger at all is the same named absence" "rung-x"
    exits 0
    says "ledger not seeded:"
    says "consult: WILL RUN (no seeded row for tree "
}

# CRITERION 47.3: the prediction is honest against the loop — both directions,
# in one case, through the seam the loop's banner prints from (see the header
# above for the half this cannot reach).
case_the_prediction_matches_the_loops_own_verdict() {
    fresh_source "ignores-dotenv" "already-up-to-date"
    local ledger key seam

    run_it "the prediction matches the loop's own verdict (phase A: derive)" "rung-x"
    exits 0
    ledger=$(seed_source_ledger 1 0)
    key=$(plant_builder_row "$DEST" "$CONSULT_SCOPE" "$ledger") || key=""
    if [ -z "$key" ]; then
        bad "could not plant a builder row at this clone's key"
        return
    fi

    # DIRECTION ONE — predicted HIT, and the consult hits.
    run_it "the prediction matches the loop's own verdict (predicted hit)" "rung-x"
    exits 0
    says "consult: EXPECTED HIT ${key}"
    seam=$(loop_seam_verdict "$DEST" "$CONSULT_SCOPE")
    is "${seam%% *}" "hit" "the loop's consult in the clone that was predicted a hit"
    is "${seam#* }" "$key" "the key that consult hits on"

    # DIRECTION TWO — main moves, the prediction says WILL RUN, and the consult
    # misses ON THE TREE. A prediction that were right only one way would be a
    # line nobody could act on.
    echo "main moved under the prediction" >>"${SRC}/tracked.txt"
    git -C "$SRC" add tracked.txt
    git -C "$SRC" commit -q -m "main moved under the prediction"
    run_it "the prediction matches the loop's own verdict (predicted run)" "rung-x"
    exits 0
    says "consult: WILL RUN (union differs: 1 commit(s) on main since the fold "
    seam=$(loop_seam_verdict "$DEST" "$CONSULT_SCOPE")
    is "${seam%% *}" "miss" "the loop's consult in the clone that was predicted a run"
    # THE TOKEN IS `tree`, AND THE ROW ABOVE IS WHY IT CAN BE. A commit on main
    # moves both key halves — the tree, and the environment fingerprint, which
    # carries `head=` and `merge-base=` among its six components — so the
    # three-line match finds nothing and the answer comes from the COMPONENT
    # pass, which ranks a banked row by those fields and names `tree` when the
    # revisions are the only thing that moved. That pass needs a row that
    # carries components, which `plant_builder_row` now writes exactly as
    # `loop_ledger_record` does. An earlier draft planted a row without them,
    # got `unmatched`, and asserted it — a case codifying its own fixture's
    # shortcut, caught by a verification against a real banked row on a real
    # clone (`tree`, with `since banked head <sha>: N path(s) changed`).
    case "${seam#* }" in
    tree*) ok "the consult misses on the TREE — the banked row carries components and the attributor ranks it" ;;
    unmatched*) bad "the consult is unmatched: the planted row carries no components, so the attributor could not rank it" ;;
    *) bad "the consult missed on '${seam#* }' — neither of the two readings this case knows" ;;
    esac
}

# CRITERION 47.4 (R3-F2x): never across an environment change. The prediction
# reads the tree and says so; the env half is measured when the loop runs.
case_an_env_change_is_never_a_hit_whatever_the_prediction() {
    fresh_source "ignores-dotenv" "already-up-to-date"
    local ledger key seam tweaked

    run_it "an env change is never a hit (phase A: derive)" "rung-x"
    exits 0
    ledger=$(seed_source_ledger 1 0)
    key=$(plant_builder_row "$DEST" "$CONSULT_SCOPE" "$ledger") || key=""
    if [ -z "$key" ]; then
        bad "could not plant a builder row at this clone's key"
        return
    fi

    run_it "an env change is never a hit whatever the prediction" "rung-x"
    exits 0
    says "consult: EXPECTED HIT ${key}"
    # THE WORDING NEVER CLAIMS THE ENV HALF — asserted, because a prediction
    # that read as a promise is the thing R3-F2x paid for.
    says "the environment and the scope halves are measured when the loop runs"

    # ONE VALUE IN THE CLONE'S OWN .env, CHANGED. The file is the clone's — the
    # source is never touched, here as everywhere in this instrument.
    tweaked="${DEST}/.env.tweaked-by-the-drive"
    awk '{ if ($0 ~ /^ZITADEL_PAT=/) print "ZITADEL_PAT=changed-by-the-drive"; else print }' \
        "${DEST}/.env" >"$tweaked"
    mv "$tweaked" "${DEST}/.env"
    if grep -qF "changed-by-the-drive" "${DEST}/.env"; then
        ok "the clone's .env really did change"
    else
        bad "the .env rewrite planted nothing — this case would pass vacuously"
        return
    fi

    seam=$(loop_seam_verdict "$DEST" "$CONSULT_SCOPE")
    is "${seam%% *}" "miss" "the loop's consult after one .env value moved"
    case "${seam#* }" in
    env*) ok "the consult misses on the ENV half, exactly as R3-F2x requires" ;;
    *) bad "the consult missed on '${seam#* }', not on the environment" ;;
    esac
}

echo "== test_verify_start — driving scripts/verify_start.sh"
echo "   scratch: ${WORK}"

case_a_piped_stdout_is_refused
case_an_unknown_option_is_refused
case_no_branch_at_all_is_refused
case_a_branch_this_checkout_does_not_have_is_refused
case_the_happy_path_clones_merges_derives_and_ends_clean
case_the_clone_carries_the_hooks_path
case_the_database_name_is_asked_for_and_matches_db_sh
case_an_exported_database_name_does_not_reach_the_clone
case_the_zitadel_carry_announces_names_and_never_values
case_an_empty_primary_carries_nothing_and_says_so
case_a_primary_with_no_env_at_all_says_so
case_a_dirty_source_checkout_is_refused_and_nothing_is_cloned
case_an_untracked_log_in_the_source_is_not_dirt
case_a_planted_stray_in_the_clone_is_refused_by_name
case_a_repository_that_does_not_ignore_dotenv_is_refused_at_step_4
case_an_occupied_destination_is_refused
case_a_conflicting_rung_branch_is_an_exit_1_naming_the_paths
case_it_never_reads_the_environment_file_into_its_own_shell
case_the_clone_is_given_a_local_main_ref_at_the_verified_sha
case_the_clone_records_its_fold_point_as_refs_djb_base
case_the_loop_ledger_is_seeded_and_the_counts_are_exact
case_a_source_with_no_loop_ledger_is_a_named_absence
case_the_seed_never_writes_to_the_source
case_step_four_is_still_green_over_the_seeded_file
case_the_venv_is_provisioned_before_the_seed_and_the_order_is_asserted
case_no_sync_skips_the_step_and_says_the_seed_cannot_hit
case_a_failing_sync_is_could_not_look_and_seeds_nothing
case_a_seeded_row_is_a_hit_once_the_venv_exists
case_the_verdict_key_ignores_the_provisioned_venv
case_docs_only_dirt_in_the_source_is_announced_and_the_clone_proceeds
case_docs_dirt_mixed_with_code_dirt_is_still_refused_naming_both
case_the_narrowing_does_not_reach_the_verdict_key_guard
case_a_folded_branch_predicts_a_hit
case_main_moved_after_the_fold_predicts_a_run_and_counts
case_no_seeded_row_is_a_named_absence
case_the_prediction_matches_the_loops_own_verdict
case_an_env_change_is_never_a_hit_whatever_the_prediction

echo
echo "== ${PASSED} passed, ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another case —
# see section 5 of the preamble for why saying so is load-bearing.
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
