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
# Fresh clone to running, idempotently. Safe to run again at any time, and safe
# to run from a second worktree while the first one's stack is up: compose.yaml
# pins the project name, so every checkout of this repository sees the same
# three containers instead of trying to start its own on the same ports.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# >>> step-wall >>>
# THE FIRST THING A STRANGER RUNS PRINTS A NUMBER. Every step says
# how long it took and the run says its total, because "the first ten minutes"
# was an estimate nobody could check: every duration in the ledgers for this
# script was hand-copied from somebody's terminal, and a hand-copied number is
# a number nobody can re-measure.
#
# THE CLOCK IS `scripts/rung_start.sh`'s, COPIED — not a third one. That file
# owns the portability ladder below (bash 5's EPOCHREALTIME · GNU date's
# `%s%3N` · perl · python3 · whole seconds, declared when it is the one used)
# and the argument for each rung of it is in its own header, above its
# `now_ms`. Principle 13: one derivation of one number. If this ladder is ever
# wrong, it is wrong in `rung_start.sh` first and this block is re-copied —
# never patched here alone. The line GRAMMAR is the gate's `leg` grammar
# (`scripts/check.sh`'s `leg`/`leg_done`: `  (<name>: <n>s)`), because these
# steps carry names rather than ordinals; the number's resolution is
# `rung_start.sh`'s `fmt_ms`, so a fast step reads `0.31s` instead of `0s`.
#
# THE CLOSE IS DEFERRED — `step` closes the step before it, and `setup_total`
# closes the last one — so a step that exits mid-way through under `set -e`
# prints no elapsed at all rather than a time for work that did not finish.
CLOCK=""
_probe=$(date +%s%3N 2>/dev/null || echo x)
if [ -n "${EPOCHREALTIME:-}" ]; then
    CLOCK=bash5
elif case "$_probe" in '' | *[!0-9]*) false ;; *) true ;; esac; then
    CLOCK=gnudate
elif command -v perl >/dev/null 2>&1; then
    CLOCK=perl
elif command -v python3 >/dev/null 2>&1; then
    CLOCK=python3
else
    CLOCK=seconds
fi

now_ms() {
    case "$CLOCK" in
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

fmt_ms() {
    awk -v ms="$1" 'BEGIN { printf "%.2fs", ms / 1000 }'
}

STEP_NAME=""
STEP_START=0
RUN_START=$(now_ms)

step_end() {
    [ -n "$STEP_NAME" ] || return 0
    printf '  (%s: %s)\n' "$STEP_NAME" "$(fmt_ms $(($(now_ms) - STEP_START)))"
    STEP_NAME=""
}

step() {
    step_end
    printf '\n== %s\n' "$1"
    STEP_NAME="$1"
    STEP_START=$(now_ms)
}

# The last line of a run, and it is the last line on purpose: the number a
# reader came for is the one under the guidance block, where the eye stops.
setup_total() {
    step_end
    printf '\nsetup: total %s\n' "$(fmt_ms $(($(now_ms) - RUN_START)))"
    if [ "$CLOCK" = "seconds" ]; then
        printf '  (clock resolution: whole seconds — no sub-second clock on this host)\n'
    fi
}
# <<< step-wall <<<

# --- Guarded temp files, fixed as a class ----------
# EVERY temp file this script makes holds a live credential: `env_set` stages
# the whole of .env (the Zitadel PAT included) on each call, `pat_file` holds
# the machine PAT, and `seed_log` is the tee of a first run's freshly-minted
# OAuth client secrets. Each site used to carry a bare `mktemp` with an `rm` on
# its happy path only, so under `set -euo pipefail` any failure — or a Ctrl-C —
# between the two lines walked past the `rm` and left the credential in $TMPDIR
# for nobody to rotate. Three sites at the time, one bug, so one fix: this
# helper, and nobody calls `mktemp` directly. THE SITES ARE NOT NUMBERED and
# nothing here counts them — a count in a comment goes stale without the comment
# changing, which is the same reason `scripts/check.sh`'s drive registrations
# carry no ordinal. What binds is the rule: no `mktemp` outside this helper.
#
# The registry is a private DIRECTORY rather than a list of paths, which is what
# lets the whole thing live inside one function: every call appends a file to
# it, cleanup is one `rm -rf` covering every call past and future, and there is
# no array to keep in step (nor bash 3.2's unset-array trap under `set -u`).
# `mktemp -d` makes it 0700, so the credentials are owner-only for their whole
# life rather than sitting in a world-readable /tmp between two lines.
#
# The trap is armed at FIRST USE — inside the helper, before it hands back a
# path — so no failure can land between creating a file and arming its removal.
# It is armed exactly once and never re-armed, because `trap` REPLACES rather
# than accumulates: a second `trap ... EXIT` anywhere below would silently
# disarm this one. Do not add one. INT/TERM/HUP `exit` rather than clean up
# themselves, which runs the EXIT trap on the way out — one cleanup path, not
# four.
#
# **It writes into a variable you name and prints nothing, and that is not a
# style choice.** `path="$(make_tmp)"` would run the whole helper in a command
# substitution — a SUBSHELL — where `DJB_TMP_DIR` and the trap are set on a
# shell that exits one microsecond later. Every call would make its own
# directory, arm a trap nobody will ever run, and leave the lot behind: the
# guard reading as coverage while covering nothing, which is worse than the bare
# `mktemp` it replaced. `printf -v` assigns in THIS shell; bash's dynamic
# scoping means the name may be a caller's `local`, which is what `env_set`
# relies on.
#
# What survives this: `kill -9`. SIGKILL cannot be trapped by any shell, so a
# hard kill still strands whatever was live at that instant. That is the
# irreducible residue, and it is why the per-site `rm` on the happy path stays:
# it keeps the window two adjacent lines wide rather than the whole run.
DJB_TMP_DIR=""

# Usage: make_tmp <variable-name>   — sets that variable to a fresh 0700 path.
make_tmp() {
    local __djb_target="$1"
    if [ -z "${DJB_TMP_DIR}" ]; then
        DJB_TMP_DIR="$(mktemp -d)"
        trap 'rm -rf "${DJB_TMP_DIR}"' EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM HUP
    fi
    printf -v "$__djb_target" '%s' "$(mktemp "${DJB_TMP_DIR}/tmp.XXXXXXXX")"
}

# The compose services this repository needs, and where each publishes.
# The stack a fresh clone needs up. MAILPIT IS IN THIS LIST BECAUSE
# `compose.yaml` SAYS IT IS THE CONTRACT: "every email the product sends
# on a laptop, caught and readable at http://127.0.0.1:8025 instead of
# delivered". A setup that brought up everything except the mail catcher left
# that promise true only for whoever thought to start it by hand — and the
# failure it exists to prevent is a laptop sending a real invitation to a real
# customer, which is exactly the kind of thing nobody starts a container for
# until after it has happened. It declares a healthcheck like every other
# service here, so `wait_healthy` covers it with no special case.
# MINIO AND MEILISEARCH JOINED LATER, each in the rung that gave it a reader —
# NOT when the containers themselves were first added, deliberately: adding a
# container to `compose.yaml` with nothing dialling it does not make a service
# a fresh clone is told it needs. Real storage tests put real bytes through
# MinIO; real engine tests drive Meilisearch live — a laptop without
# them up now FAILS those tests rather than skipping them, which is the whole
# reason they belong here.
SERVICES=(db redis temporal zitadel mailpit minio meilisearch)

# Health of one compose service, as compose reports it. Empty when the service
# is not running at all.
service_health() {
    # READ WHOLE, THEN SLICE. `docker compose ps … | head -1` under this file's
    # `set -o pipefail` orphans compose mid-write once its output passes the
    # kernel's 64 KiB pipe buffer, and the pipeline's 141 would kill setup at a
    # line that had already read the health it wanted. `|| true` keeps a compose
    # that is not running from being fatal, which is what the old `2>/dev/null`
    # plus an empty answer already meant.
    local reported
    reported="$(docker compose ps --format '{{.Health}}' "$1" 2>/dev/null || true)"
    printf '%s\n' "${reported%%$'\n'*}"
}

# True when every service is already up and healthy — which is the normal case
# in a second worktree, and the case `docker compose up` used to make worse.
stack_is_healthy() {
    local service
    for service in "${SERVICES[@]}"; do
        [ "$(service_health "$service")" = "healthy" ] || return 1
    done
    return 0
}

# Sets KEY=VALUE in .env, in place: replacing the line if the key is already
# there, appending it if it is not. Never duplicates a key, never reorders the
# file, and never touches .env.example.
env_set() {
    local key="$1" value="$2" tmp
    # A `make_tmp` site. The `rm` below is the happy path; `make_tmp`'s registry is
    # what covers the failing one — the redirect into .env going wrong, a
    # Ctrl-C, an `awk` that dies — each of which used to strand a full copy of
    # .env, PAT and all.
    make_tmp tmp
    if grep -q "^${key}=" .env; then
        awk -v k="$key" -v v="$value" '
            index($0, k "=") == 1 { print k "=" v; next }
            { print }
        ' .env >"$tmp"
    else
        cat .env >"$tmp"
        printf '%s=%s\n' "$key" "$value" >>"$tmp"
    fi
    cat "$tmp" >.env
    rm -f "$tmp"
}

# >>> env-sync >>>
# THE ENVIRONMENT FILE IS REGENERATED FROM `.env.example`, NOT LEFT ALONE — and
# the reason is a measurement rather than tidiness. `loop_env_fingerprint` in
# `scripts/gate_ledger.sh` hashes EVERY LINE of `.env`, in file order, comments
# and blank lines included, minus the keys a deriver declares. A verifier's
# clone builds its own `.env` from `.env.example` and substitutes the derived
# database name and the identity carry IN PLACE, so a builder's checkout can hit
# that clone's banked verdict only while its own `.env` is the same skeleton.
# Leaving an existing file alone made every checkout drift one line further from
# the example on every merge that touched it. Measured on this box on
# 2026-09-07: a checkout whose `.env` predated one added block differed from its
# own clone's by 592 lines and was dozens of keys short, and the consult
# re-measured the whole suite (162s) instead of reusing a green verdict (1s).
#
# ADDING THE MISSING KEYS WOULD NOT HAVE FIXED IT, and that was the first shape
# proposed. The digest is order- and comment-sensitive, so a file carrying every
# key in the wrong order with the old prose around it still differs. The only
# shape that hits is the example's bytes with this checkout's values in the
# example's positions.
#
# WHAT IT PRESERVES, and what it deliberately does not:
#
#   * a key in both files whose VALUE differs keeps the file's value, at the
#     EXAMPLE's position;
#   * a key the file has and the example does not is kept — appended at the end
#     under one marker comment, in the order it appeared — never dropped;
#   * a COMMENT the file carries and the example does not is NOT kept. The
#     example owns the prose, and that is the whole of why the digest can agree;
#   * a key the file carries TWICE collapses to its last value, once, at the
#     example's position — dotenv's own last-wins rule, applied where the file
#     is rebuilt rather than read.
#
# The previous file is copied to `.env.previous` (mode 600; ignored by the
# `.env.*` line in `.gitignore`) BEFORE anything is written, so one run is
# reversible by hand. NOTHING HERE PRINTS A VALUE: the block names keys and
# counts them, because the first credential this file carries is a machine PAT
# and a setup log is pasted into reports.
ENV_SYNC_MARKER='# --- kept from a previous .env: not in .env.example ---'

# env_sync_classify <env-file> <example-file> — one `A|P|K <KEY>` line per key
# that would be added, preserved or kept. NAMES ONLY, never values.
#
# `FILENAME == envfile` rather than the usual `FNR == NR`: an EMPTY first file
# yields no records at all, so `FNR == NR` would then be true for the second
# file's first line and the example would be read as the environment. That is a
# real state here — a truncated `.env` — and it would silently classify every
# key as "kept".
env_sync_classify() {
    awk -v envfile="$1" '
        FILENAME == envfile {
            if ($0 ~ /^[A-Za-z_][A-Za-z0-9_]*=/) {
                name = $0
                sub(/=.*$/, "", name)
                if (!(name in seen)) { seen[name] = 1; order[++n] = name }
                line[name] = $0
            }
            next
        }
        {
            if ($0 ~ /^[A-Za-z_][A-Za-z0-9_]*=/) {
                name = $0
                sub(/=.*$/, "", name)
                if (name in fromexample) next
                fromexample[name] = 1
                if (!(name in seen)) print "A " name
                else if (line[name] != $0) print "P " name
            }
        }
        END {
            for (i = 1; i <= n; i++) if (!(order[i] in fromexample)) print "K " order[i]
        }
    ' "$1" "$2"
}

# env_sync_render <env-file> <example-file> — the file that SHOULD be there, on
# stdout. The example's bytes, with the environment's value substituted at the
# example's own position wherever the two disagree, and the keys the example
# does not have appended under the marker.
#
# The whole LINE is carried over, never a re-joined key and value: a value
# holding an `=` or a `#` is common in a `.env` (a URL, a password, a JSON
# fragment) and a split-then-join is where that gets quietly rewritten.
#
# ONE COMMENT IS CARRIED, AND IT IS NOT PROSE: the `# pinned` marker. It says a
# human meant the DATABASE_NAME pin below it (scripts/db.sh, THE MARKER'S
# GRAMMAR), and `setup.sh`'s pin block — run after this — keeps a marked pin
# and overrides an unmarked one. Dropping it with the rest of the old prose
# erased the pin it protected: the pin block then found no marker, overwrote
# the name, and told the reader to add the very line this function had just
# removed. So the marker line directly above the OPERATIVE `DATABASE_NAME=`
# line (the last one — django-environ's last-wins reading, and
# `db_pin_marked`'s) is printed verbatim directly above wherever that line is
# printed: the example's position, or the kept-at-end block. The grammar is
# `DB_PIN_MARKER_ERE` from scripts/db.sh, handed in through ENVIRON — never a
# second spelling here — and a fence sourced without it refuses (exit 2)
# rather than render a file that quietly drops a pin.
#
# A FILE WITH NO MARKER RENDERS BYTE-IDENTICAL to before. A file WITH one now
# keeps a line the example lacks, so its bytes differ from a verifier clone's
# `.env` and `loop_env_fingerprint` (scripts/gate_ledger.sh) keys it apart: a
# pinned checkout reuses fewer banked verdicts, never a wrong one. Accepted —
# a pinned checkout already opens a different database from its clone.
env_sync_render() {
    if [ -z "${DB_PIN_MARKER_ERE:-}" ]; then
        echo "env-sync: the # pinned grammar is not loaded — scripts/db.sh owns it and was not sourced; refusing to render a .env that would drop a pin." >&2
        return 2
    fi
    DB_PIN_MARKER_ERE="$DB_PIN_MARKER_ERE" awk -v envfile="$1" -v marker="$ENV_SYNC_MARKER" '
        FILENAME == envfile {
            if ($0 ~ /^[A-Za-z_][A-Za-z0-9_]*=/) {
                name = $0
                sub(/=.*$/, "", name)
                if (!(name in seen)) { seen[name] = 1; order[++n] = name }
                line[name] = $0
                if (name == "DATABASE_NAME") pinmark = previous
            }
            previous = ($0 ~ ENVIRON["DB_PIN_MARKER_ERE"]) ? $0 : ""
            next
        }
        {
            if ($0 ~ /^[A-Za-z_][A-Za-z0-9_]*=/) {
                name = $0
                sub(/=.*$/, "", name)
                fromexample[name] = 1
                if (name in seen) {
                    if (name == "DATABASE_NAME" && pinmark != "") print pinmark
                    print line[name]
                    next
                }
            }
            print
        }
        END {
            any = 0
            for (i = 1; i <= n; i++) if (!(order[i] in fromexample)) any = 1
            if (any) {
                print ""
                print marker
                for (i = 1; i <= n; i++) if (!(order[i] in fromexample)) {
                    if (order[i] == "DATABASE_NAME" && pinmark != "") print pinmark
                    print line[order[i]]
                }
            }
        }
    ' "$1" "$2"
}

# env_sync_from_example — the environment step's one job. Exit 0 written (or
# already correct) · 1 there is no `.env.example` and nothing was touched.
env_sync_from_example() {
    local example=.env.example target=.env previous=.env.previous
    local tmp cls count added preserved kept added_names preserved_names kept_names

    if [ ! -f "$example" ]; then
        echo "env-sync: there is no ${PWD}/${example} — nothing to derive an environment from." >&2
        echo "env-sync: .env was not written and was not touched." >&2
        return 1
    fi

    if [ ! -f "$target" ]; then
        # A `make_tmp` site, and the same argument as `env_set`'s: what is staged
        # here is about to become a file full of credentials.
        make_tmp tmp
        cat "$example" >"$tmp"
        cat "$tmp" >"$target"
        rm -f "$tmp"
        count=$(grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' "$example" || true)
        echo "env-sync: no .env — copied .env.example to .env, ${count} key(s)"
        echo "env-sync: 0 value(s) preserved in place"
        echo "env-sync: 0 key(s) not in .env.example kept at the end"
        echo "env-sync: no previous .env — .env.previous not written"
        return 0
    fi

    make_tmp cls
    env_sync_classify "$target" "$example" >"$cls"
    added=$(grep -c '^A ' "$cls" || true)
    preserved=$(grep -c '^P ' "$cls" || true)
    kept=$(grep -c '^K ' "$cls" || true)
    added_names=$(sed -n 's/^A //p' "$cls" | tr '\n' ' ')
    preserved_names=$(sed -n 's/^P //p' "$cls" | tr '\n' ' ')
    kept_names=$(sed -n 's/^K //p' "$cls" | tr '\n' ' ')

    make_tmp tmp
    if ! env_sync_render "$target" "$example" >"$tmp"; then
        rm -f "$tmp" "$cls"
        return 2
    fi

    # THE PREVIOUS FILE FIRST, and the mode before the content: a `>` creates
    # the file with the umask's bits, so filling it and then chmod-ing it leaves
    # a whole copy of the environment world-readable for the width of one `cat`.
    : >"$previous"
    chmod 600 "$previous"
    cat "$target" >"$previous"

    if cmp -s "$tmp" "$target"; then
        rm -f "$tmp" "$cls"
        echo "env-sync: .env already matches .env.example's shape — nothing to do"
        echo "env-sync: .env.previous written"
        return 0
    fi

    cat "$tmp" >"$target"
    rm -f "$tmp" "$cls"

    echo "env-sync: ${added} key(s) added from .env.example${added_names:+: ${added_names% }}"
    echo "env-sync: ${preserved} value(s) preserved in place${preserved_names:+: ${preserved_names% }}"
    echo "env-sync: ${kept} key(s) not in .env.example kept at the end${kept_names:+: ${kept_names% }}"
    echo "env-sync: .env.previous written"
}
# <<< env-sync <<<

# Waits for a compose service to report healthy. Every service in compose.yaml
# declares a healthcheck, so "up" is never mistaken for "ready".
wait_healthy() {
    local service="$1" attempts="${2:-90}"
    printf 'waiting for %s' "$service"
    for _ in $(seq 1 "$attempts"); do
        if [ "$(service_health "$service")" = "healthy" ]; then
            printf ' ready\n'
            return 0
        fi
        printf '.'
        sleep 1
    done
    printf '\n'
    echo "${service} did not become healthy; check 'docker compose logs ${service}'" >&2
    return 1
}

# >>> services >>>
# THE STACK IS PULLED BEFORE IT IS STARTED, AND A PULL THAT FAILS IS A REFUSAL
# — exit 2, naming the image and the registry — rather than the shape this used
# to have, which was `docker compose up -d` discovering the same thing halfway
# through a start and saying so in compose's vocabulary, or not saying it at all
# and leaving `wait_healthy` to count to 180 against a container that was never
# going to exist.
#
# The measurement behind it (2026-09-12): `compose.yaml` pinned
# `minio/minio:RELEASE.2025-09-07T16-13-09Z`, Docker Hub stopped serving that
# tag, and the first thing a fresh clone runs stopped working. The pin moved to
# quay.io; this step is what makes the NEXT registry to drop a tag a refusal
# that names the image instead of a setup that hangs. A registry is a vendor
# behind a pin (principle 5) and an external system is untrusted (principle 4):
# the failure gets a handling path, not a timeout.
#
# WHY `compose pull` RATHER THAN `docker manifest inspect`: `pull` is what `up`
# does anyway, so this adds a name for a failure that was already going to
# happen rather than a second network act; `manifest inspect` needs experimental
# mode on some daemons (`deploy/provision.sh` records the same thing about it).
#
# The reuse path pulls NOTHING. A second worktree finding the stack already
# healthy is the normal case, and a pull there would spend a fresh clone's
# network on every `setup.sh` in the house.
services_up() {
    if stack_is_healthy; then
        # The ports this line names are what it is vouching for; mailpit's 8025
        # belongs here too, or the message under-reports the stack it just
        # called healthy. MinIO's 9000 (S3 API) and 9001 (console) and
        # Meilisearch's 7700 joined under the same rule.
        echo "reusing running stack (compose project djangobootstrap, ports 5432/6379/7233/8081/8025/9000/9001/7700)"
        return 0
    fi

    local pull_log="" rc=0
    make_tmp pull_log
    echo "pulling the images before starting anything — a registry that stopped"
    echo "serving a pinned tag is a refusal here, not a timeout in \`up\`"
    docker compose pull "${SERVICES[@]}" >"$pull_log" 2>&1 || rc=$?
    sed 's/^/  | /' "$pull_log"

    if [ "$rc" -ne 0 ]; then
        echo "!! setup: COULD NOT LOOK — \`docker compose pull\` exited ${rc}, so this" >&2
        echo "   checkout cannot tell whether its images exist. NOTHING WAS STARTED:" >&2
        echo "   \`docker compose up\` was not run and no service was waited on." >&2
        echo "   The image references this checkout asks for, each with the registry" >&2
        echo "   host it would be fetched from:" >&2
        services_image_census >&2
        echo "   Read the pull transcript above for the one that failed. A registry" >&2
        echo "   that has stopped serving a pinned tag (Docker Hub and" >&2
        echo "   minio/minio:RELEASE.2025-09-07T16-13-09Z, 2026-09-12) looks exactly" >&2
        echo "   like this, and the fix is in compose.yaml beside the pin." >&2
        exit 2
    fi

    docker compose up -d "${SERVICES[@]}"
    local service
    for service in "${SERVICES[@]}"; do
        # Zitadel's first start on an empty database runs every migration and
        # then the first-instance bootstrap; it is the slow one here.
        wait_healthy "$service" 180
    done
}

# Every image this checkout's services name, with the registry each would be
# fetched from — printed by the refusal above so the reader does not have to
# read compose's transcript to learn which vendor is involved. Derived from the
# rendered compose file, never a hand list: a hand list is how the census stops
# naming the service that was added last.
services_image_census() {
    local image
    while IFS= read -r image; do
        [ -n "$image" ] || continue
        printf '     %s   (registry %s)\n' "$image" "$(image_registry_host "$image")"
    done < <(docker compose config --images "${SERVICES[@]}" 2>/dev/null || true)
}

# Docker's own rule for reading a reference: the first path segment is a
# registry host only when it carries a dot or a colon, or is exactly
# `localhost`. That is the whole difference between `minio/minio` (Docker Hub)
# and `quay.io/minio/minio` (quay.io), and it is the difference the registry
# move turned on.
image_registry_host() {
    local ref="$1" first="${1%%/*}"
    case "$ref" in
    */*)
        case "$first" in
        *.* | *:* | localhost)
            printf '%s\n' "$first"
            return 0
            ;;
        esac
        ;;
    esac
    printf 'docker.io\n'
}
# <<< services <<<

# >>> local-main >>>
# ensure_local_main — the first step, and the reason it is first.
#
# A clone of a PUBLISHED TAG is the shape every consumer's first clone takes:
#
#   git clone --branch <a published tag> <the repository>
#
# and git leaves that checkout on a DETACHED HEAD with no local `refs/heads/main`
# at all. Measured on a real tag clone, 2026-09-13: the fifteenth builder's
# first `./scripts/check.sh --loop` refused in 0.8 s —
#
#   this checkout has NO local refs/heads/main, so the --loop scope has no
#   fork point to derive the active rung from.
#
# — a refusal that is EXEMPLARY and stays exactly as it is (`scripts/loop_tier.sh`;
# its own argument: a thin basis is not a small answer, it is the wrong one).
# What was wrong was not the refusal but the trap in front of it, and a trap is
# closed one step earlier: the first thing a stranger runs now gives the
# checkout the ref every scope tool in this tree reads by name.
#
# IT IS THE FIRST STEP BECAUSE THE STEP AFTER IT PERSISTS A DERIVED NAME. The
# environment step writes `DATABASE_NAME` into `.env` and that name carries the
# BRANCH (`scripts/db.sh`); on a detached HEAD there is no branch to carry, so a
# `.env` written before this step would pin a detached-shaped name for the life
# of the checkout. The ref has to exist before the first file that remembers it.
#
# IT CREATES NOTHING WHERE `main` ALREADY EXISTS, and that is the common case on
# a working box: every linked worktree of this repository shares the common git
# dir, so `rev-parse refs/heads/main` answers there and this step is a silent
# no-op — no `branch`, no `switch`, nothing printed. A `verify_start.sh` clone
# is the same: that script creates `main` at the verified sha itself, on
# purpose, and this step finds it already there.
#
# `main` AT HEAD, NEVER AT `origin/main`'s TIP. A stranger who cloned v2.0.0
# asked for v2.0.0; `scripts/rung_start.sh` resets a worktree to `main`, so a
# `main` planted at the remote tip would quietly move them off the tag they
# chose. The sentence below prints the one-line move for anyone who wants the
# tip instead.
#
# A GIT THAT FAILS HERE IS EXIT 2 NAMING THE COMMAND, never a silent continue:
# everything downstream — the database name, the loop scope, the secret scan's
# basis — reads the ref this step was supposed to make, and each of them would
# fail later saying something else.
ensure_local_main() {
    local head_sha short
    if git rev-parse -q --verify refs/heads/main >/dev/null 2>&1; then
        return 0
    fi
    if ! head_sha=$(git rev-parse -q --verify HEAD 2>/dev/null) || [ -z "$head_sha" ]; then
        # An unborn HEAD: `git init` with nothing committed. There is no commit
        # to place a branch on, and nothing else this early needs one.
        echo "no commit to place main on — skipping"
        return 0
    fi
    git branch main HEAD || {
        echo "setup.sh: \`git branch main HEAD\` failed — this checkout has no local" >&2
        echo "  refs/heads/main and one could not be created. Everything below derives" >&2
        echo "  from that ref; a setup that continued here would fail later saying" >&2
        echo "  something else." >&2
        exit 2
    }
    if ! git symbolic-ref -q HEAD >/dev/null 2>&1; then
        git switch main || {
            echo "setup.sh: \`git switch main\` failed — the ref was created but this" >&2
            echo "  checkout is still on a detached HEAD, so the database name has no" >&2
            echo "  branch to derive from (scripts/db.sh)." >&2
            exit 2
        }
    fi
    short=$(git rev-parse --short main)
    echo "main created at ${short} (this checkout had no local main — a tag clone; the --loop scope and the database name derive from it; to move to the tip: git fetch origin main && git reset --hard FETCH_HEAD)"
}
# <<< local-main <<<

step "local main"
ensure_local_main

step "environment file"
# db.sh FIRST: it owns the `# pinned` grammar (`DB_PIN_MARKER_ERE`) the render
# below carries through the rebuild, and it is the same file the database step
# further down relies on — sourced once, here, after the local-main step has
# settled the ref its derivation reads.
# shellcheck source=scripts/db.sh
source "${ROOT}/scripts/db.sh"
# THE STEP REGENERATES rather than leaves alone, because the per-rung ledger's
# env-file component (`loop_env_fingerprint` in `scripts/gate_ledger.sh`) hashes
# every line of `.env` in file order, comments included — so a checkout whose
# file predates a line of `.env.example` cannot reuse a verdict banked by a
# clone that built its `.env` from the example. Values are carried over in
# place; keys the example does not have are kept at the end. The argument in
# full, and what it does not preserve, is above `env_sync_from_example`.
env_sync_from_example
# Owner-only, every run and not just the run that created it (SEC-1's INFO,
# ridden here because this is where the file's owner is). Everything this
# script goes on to write into .env is a credential — the Zitadel PAT above
# all — and `cp` gives the copy the umask's mode, which on a normal laptop is
# world-readable. `chmod` on a file that is already 600 is a no-op, so this is
# safe to re-run and safe on a .env somebody else made.
chmod 600 .env

step "python dependencies"
uv sync

step "services"
services_up

step "zitadel machine credential"
# Zitadel mints the platform service account's personal access token exactly
# once, on its first start, into a named docker volume — never into this tree.
# It belongs in .env, which is gitignored, because that is where settings and
# the management client read it from.
# A `make_tmp` site: the machine PAT. On a run that reaches here first, this is
# what arms the one EXIT trap, so the file is covered before the line has
# finished returning — and
# the trap it arms covers `seed_log` further down, and `env_set`'s per-call
# staging file, without any of them being named here (see `make_tmp`).
pat_file=""   # the out-parameter make_tmp fills; declared so `set -u` and shellcheck both see it
make_tmp pat_file
# THE OPERATOR'S VALUE IS ASKED ABOUT FIRST, and that ordering is the
# whole fix. This used to test the compose volume first and write
# unconditionally when it answered — so on any machine whose Zitadel had
# bootstrapped a PAT (which is every laptop running this stack) the
# "already in .env; leaving it alone" branch below was UNREACHABLE, and an
# operator pointing this checkout at an externally-managed Zitadel had their
# credential overwritten by the local container's on every run of a script
# whose whole promise is that it is safe to re-run.
#
# The same shape as a pin elsewhere in this repository, refused for the same
# reason: a value a human put somewhere is not this script's to replace
# without being asked.
# `.env` wins; the volume fills a gap.
if grep -q "^ZITADEL_PAT=." .env; then
    echo "ZITADEL_PAT already in .env; leaving it alone"
    # Said out loud, because "leaving it alone" is only reassuring if the
    # reader knows there WAS something else on offer. A silent no-op and a
    # no-op nobody could have noticed look identical in a transcript.
    if docker compose cp zitadel:/zitadel/bootstrap/machine.pat "$pat_file" >/dev/null 2>&1; then
        echo "  (this compose Zitadel offers its own bootstrap PAT; .env's value wins —"
        echo "   delete the ZITADEL_PAT line and re-run to adopt the container's)"
    fi
elif docker compose cp zitadel:/zitadel/bootstrap/machine.pat "$pat_file" >/dev/null 2>&1; then
    env_set ZITADEL_PAT "$(tr -d '\r\n' <"$pat_file")"
    echo "ZITADEL_PAT written to .env from the zitadel_bootstrap volume"
else
    echo "no PAT: this Zitadel instance was bootstrapped without one." >&2
    echo "Issue one for the machine user, or reset the instance (drop the" >&2
    echo "zitadel database and the zitadel_bootstrap volume), then run this again." >&2
fi
rm -f "$pat_file"

step "sign-in door (classic login)"
# THE INSTANCE HALF, and it exists because the compose line is
# only the OTHER half. `compose.yaml` pins
# ZITADEL_DEFAULTINSTANCE_FEATURES_LOGINV2_REQUIRED=false; `DefaultInstance` is
# applied WHEN THE INSTANCE IS CREATED, so that line is the whole fix on a
# fresh volume and does NOTHING to an instance that already exists — Zitadel's
# own defaults.yaml: once a feature is set on the instance, system-level
# feature settings are ignored until instance features are reset. Every laptop
# that ran this stack before the compose line landed carries such an instance,
# and on it the browser sign-in button redirects to
# `/ui/v2/login/login?authRequest=…` and gets a 404, because Login V2 is a
# separate container this stack does not ship: the quickstart's first step,
# invitation acceptance and the /mcp OAuth flow are all dead behind it. The
# feature API is the only route into an existing instance, so this step drives
# it. The reasoning, the spelling read out of the image, and the adoption
# trigger live at `deploy/compose.yaml`'s copy of that key — one home.
#
# IDEMPOTENT: it reads first and writes only when it finds the defect, so the
# normal case is one line saying nothing needed doing.
#
# NEVER FATAL, argued the other way. Identity may legitimately
# be unbootstrapped on this laptop — no PAT, no instance, an operator pointing
# at something that is not up yet — and `zitadel_seed` below is already the step
# that reports a shut identity door. A failure to READ or WRITE the feature here
# prints the manual command on stderr and carries on; it never fails setup.
# Single-quoted ON PURPOSE: this string is printed for a human to paste, so the
# `$ZITADEL_PAT` and `$ZITADEL_ISSUER` in it must survive as names they can read
# out of their own .env — expanding them here would print the credential.
# shellcheck disable=SC2016
login_v2_manual='curl -X PUT -H "Authorization: Bearer $ZITADEL_PAT" -H "Content-Type: application/json" -d "{\"loginV2\":{\"required\":false}}" "$ZITADEL_ISSUER/v2/features/instance"'
zitadel_pat="$(sed -n 's/^ZITADEL_PAT=//p' .env | tail -1)"
zitadel_base="$(sed -n 's/^ZITADEL_ISSUER=//p' .env | tail -1)"
if [ -z "$zitadel_base" ]; then
    zitadel_port="$(sed -n 's/^ZITADEL_EXTERNALPORT=//p' .env | tail -1)"
    zitadel_base="http://localhost:${zitadel_port:-8081}"
fi
# The PAT goes in on STDIN, through curl's own config format, rather than in an
# argument: `curl -H "Authorization: Bearer $PAT"` puts a live credential in the
# process table for anyone with `ps` for as long as the request takes. `printf`
# is a shell builtin, so it never appears in an argument list either.
if ! command -v curl >/dev/null 2>&1; then
    echo "sign-in door: curl not found, so loginV2 was not checked on this instance." >&2
    echo "  Check and repair by hand: ${login_v2_manual}" >&2
elif [ -z "$zitadel_pat" ]; then
    echo "sign-in door: no ZITADEL_PAT in .env, so loginV2 was not checked." >&2
    echo "  Repair once identity is bootstrapped: ${login_v2_manual}" >&2
else
    features="$(printf 'header = "Authorization: Bearer %s"\n' "$zitadel_pat" |
        curl -sS -K - -w '\n%{http_code}' "${zitadel_base}/v2/features/instance" 2>/dev/null || true)"
    features_code="$(printf '%s' "$features" | tail -1)"
    features_body="$(printf '%s' "$features" | sed '$d')"
    if [ "$features_code" != "200" ]; then
        echo "sign-in door: could not read ${zitadel_base}/v2/features/instance (HTTP ${features_code:-none});" >&2
        echo "  loginV2 was NOT checked. If browser sign-in 404s at /ui/v2/login/…, repair by hand:" >&2
        echo "  ${login_v2_manual}" >&2
    elif ! printf '%s' "$features_body" | grep '"loginV2"' >/dev/null; then
        # THE READER DOES NOT EXIT EARLY, and the inversion is why it matters
        # most here. Under this file's `pipefail`, a quiet consumer that stops at
        # its first match leaves the producer writing into a closed pipe: the
        # producer takes SIGPIPE, the pipeline reports 141, and 141 is not zero.
        # A bare probe would then read "absent" for something present — but this
        # probe is NEGATED, so 141 sends it down THIS branch, and this branch
        # prints "shape not recognised" and SKIPS THE REAL CHECK below. The race
        # does not make the step noisy; it makes the step stop looking, while
        # printing a sentence that sounds like it looked. That is the worse
        # direction of the two, on the one step that repairs the sign-in door.
        #
        # MEASURED ON THIS BOX, not reasoned (BSD grep 2.6.0-FreeBSD, macOS):
        # it is a STEEP PROBABILITY STEP at the 64 KiB pipe buffer, not a wall.
        # Re-measured at higher counts than the first reading: a body ABOVE the
        # buffer took the wrong branch 189 times in 200 runs, and a body BELOW it
        # 1 time in 500. Neither side is certain — a macOS pipe starts at 16 KiB
        # and grows, so the boundary itself moves — and the honest statement is
        # that below the buffer the producer's write usually fits and it rarely
        # blocks, while above it the producer usually blocks and usually loses.
        # This body is an external API response and nothing bounds it under
        # 64 KiB, so the reader reads to EOF and the branch below is reached on
        # the evidence. The conversion the branch defends is unchanged; only the
        # certainty the words claimed is.
        #
        # AND THE SECOND CONDITION, re-measured when this branch folded main:
        # the reader is line-oriented and cannot decide a line it does not yet
        # hold, so a body with NO newline in it is read to EOF whatever its
        # size — 84,016 bytes on one line took the wrong branch 0/50 runs,
        # while the same bytes over 2,101 lines took it 50/50. This instance
        # answers compact JSON today, which is why the line above is BELT and
        # not repair, and it is labelled that way rather than sold as a fix.
        # It stops being belt the moment the feature API pretty-prints — a
        # change nobody would ever make with this branch in mind, which is
        # exactly the kind this reader should not be one edit away from.
        #
        # Said out loud rather than read as "already correct": a feature API that
        # stopped naming loginV2 is a shape change, and the one answer this step
        # must never give on a shape it does not recognise is reassurance.
        echo "sign-in door: the feature API answered without a loginV2 field — shape not recognised," >&2
        echo "  so nothing was checked. Read it yourself: ${zitadel_base}/v2/features/instance" >&2
    else
        login_v2="$(printf '%s' "$features_body" | tr -d ' \n' | sed -n 's/.*"loginV2":{\([^}]*\)}.*/\1/p')"
        case "$login_v2" in
        *'"required":true'*)
            echo "sign-in door: loginV2 required=true found on this instance — repairing (classic-login-pin)"
            repair_code="$(printf 'header = "Authorization: Bearer %s"\n' "$zitadel_pat" |
                curl -sS -K - -X PUT -H 'Content-Type: application/json' \
                    -d '{"loginV2":{"required":false}}' \
                    -o /dev/null -w '%{http_code}' \
                    "${zitadel_base}/v2/features/instance" 2>/dev/null || true)"
            if [ "$repair_code" = "200" ]; then
                echo "sign-in door: loginV2 required=false — classic login restored"
            else
                echo "sign-in door: the repair PUT failed (HTTP ${repair_code:-none}); browser sign-in" >&2
                echo "  will still 404 at /ui/v2/login/…. Repair by hand:" >&2
                echo "  ${login_v2_manual}" >&2
            fi
            ;;
        *)
            echo "sign-in door: loginV2 not required on this instance — already correct"
            ;;
        esac
    fi
fi

step "database for this worktree"
# scripts/db.sh was sourced at the environment step above (its marker grammar
# is what the render carries); every name below is its.
# Persist the derivation into .env, so a BARE `manage.py` — one that never
# sourced db.sh — resolves the same database every script here does. Without
# this line .env keeps whatever .env.example shipped and a stray
# `manage.py migrate` lands somewhere else entirely.
#
# RECONCILE ON EVERY RUN, UNLESS THE PIN SAYS IT MEANT IT. This line
# already wrote the derived name unconditionally — which is the reconciliation
# the build contract promises, and also, for a checkout that pinned a name on
# purpose, the same silent clobber as above (a value a human put there,
# replaced without being asked). A `# pinned` comment line directly ABOVE the
# DATABASE_NAME line is the escape: a checkout that carries it keeps its name
# and is told that it did. Its own line, never appended to the value — an
# inline comment is read INTO the name by django-environ and by
# `docker --env-file` (scripts/db.sh, "THE MARKER'S GRAMMAR").
#
# The disagreement itself is NOT silenced by the marker — `db.sh` still prints
# its notice on every source, because a pinned checkout still has two
# databases and that fact does not stop being true because somebody meant it.
# The marker governs what this script WRITES, not what any script SAYS.
#
# THE MARKER IS `db_pin_marked`'S, NOT A GREP OF OUR OWN. This block used to
# carry its own copy of the marker regex, and `rung_start.sh` carried a third.
# When the marker's grammar changed — it now lives on its OWN comment line
# above a bare value, because an inline one is read INTO the name by
# django-environ and by docker --env-file (scripts/db.sh, "THE MARKER'S
# GRAMMAR") — three copies meant three chances to leave one behind, and a
# reader left behind here is `setup.sh` silently clobbering a name a human
# pinned. `db.sh` is already sourced above; the marker has one definition.
#
# AND THE WHOLE DECISION IS `db_pin_decide`'S, NOT ONLY THE MARKER. This block
# used to ask the marker and then write `${DATABASE_NAME}` — whatever db.sh
# resolved, and db.sh lets an EXPORTED name win (rule 1). A shell that had
# sourced db.sh before the checkout moved still exported the OLD derivation,
# so an unmarked stale pin was written straight back over itself, migrated,
# and announced as this worktree's database — while the gate's db-pin leg read
# the same `.env`, found an unmarked disagreement, and refused naming this
# script as the remedy. Two tables, one cell each, pointing at each other.
# Now both read the one verdict:
#
#   DB_PIN_MARKED    left alone, and said so — unchanged
#   disagree         the pin is OVERRIDDEN: the derivation is written, the run
#                    migrates the derivation, and the line says which name it
#                    overrode and where that name came from — the .env pin,
#                    and the shell too when the shell exports the same stale
#                    name (that export is the pin's echo, not a separate
#                    choice, so it is overridden with it and the reader is told
#                    to drop it). An export naming a THIRD name is a separate
#                    choice and rule 1 keeps it for this run.
#   anything else    what db.sh resolved is written, as before
db_pin_decide
if [ -n "$DB_PIN_MARKED" ]; then
    env_pin="$(grep -E '^DATABASE_NAME=' .env | tail -1)"
    echo "DATABASE_NAME left alone — .env carries the \`# pinned\` marker"
    echo "  .env:       ${env_pin}"
    echo "  derivation: ${DATABASE_NAME}"
    echo "  This checkout's scripts will use the derivation and a bare manage.py"
    echo "  will use the pin. Remove the marker and re-run to reconcile them."
elif [ "$DB_PIN_VERDICT" = "disagree" ]; then
    overridden="$DB_PIN_VALUE"
    overridden_also=""
    if [ "${DATABASE_NAME}" = "$overridden" ]; then
        overridden_also=" (also exported in this shell)"
        DATABASE_NAME="$DB_PIN_DERIVED"
        DATABASE_NAME_SOURCE="derived"
        export DATABASE_NAME DATABASE_NAME_SOURCE
    fi
    env_set DATABASE_NAME "$DB_PIN_DERIVED"
    echo "DATABASE_NAME: the unmarked .env pin ${overridden}${overridden_also} was overridden by the derivation ${DB_PIN_DERIVED}; add \"# pinned\" above it to keep it"
    if [ -n "$overridden_also" ]; then
        echo "  This shell still exports DATABASE_NAME=${overridden}, and every script run"
        echo "  from it will open that name (scripts/db.sh rule 1): \`unset DATABASE_NAME\`"
        echo "  there, or open a new shell."
    fi
    echo "DATABASE_NAME=${DATABASE_NAME}"
else
    env_set DATABASE_NAME "${DATABASE_NAME}"
    echo "DATABASE_NAME=${DATABASE_NAME}"
fi
# Created AFTER the name is settled, never before: the block above may have
# overridden a stale exported name, and a `db_create` above it would have
# prepared the name this run no longer uses.
db_create

step "migrations"
DATABASE_NAME="${DATABASE_NAME}" uv run python manage.py migrate

step "zitadel identity configuration"
# Idempotent: the project, the browser client, the MCP resource, the
# pre-registered MCP client and a dev person. A second run — which is every run
# after the first, in every worktree sharing this instance — creates nothing and
# says `exists` for each. That is why it can live here rather than in a
# README step somebody has to remember (ADR ident-2).
#
# NOT FATAL, AND NOT SILENT EITHER. This step used to be "not fatal"
# in the strongest sense available: the failure was named on stderr, the script
# carried on, and the closing banner said "Setup complete." with exit 0. Both
# halves of that are a lie a caller acts on. A human skims for the banner; CI
# reads `$?`; and the one state a setup script must never report is "the
# machine is now what you asked for" when it is not — the identity door is shut
# and every OAuth path through /mcp is dead.
#
# So the two behaviours are separated rather than traded off. The REST of setup
# still runs — the database, the migrations, the hooks, the guidance — because
# a laptop with no PAT genuinely should end up with a working stack, and
# stopping here would take that away. What changes is the VERDICT: the failure
# is remembered in `SETUP_INCOMPLETE`, the closing banner names what did not
# happen instead of claiming completion, and the script exits non-zero.
#
# Exit 1, not 2: this script LOOKED. It ran `zitadel_seed`, the command
# answered, and the answer was a failure — "I looked and it is wrong", which is
# exit 1 everywhere in this repository. Exit 2 here stays what it is elsewhere
# (`docs/product/instruments.md`): could not look at all.
SETUP_INCOMPLETE=""
# A `make_tmp` site. Live credentials again: on a first run the seed prints the OAuth
# client secrets it has just minted, and this is the tee of that output. The
# `rm` after the block is the happy path; every other exit is covered by the
# single EXIT trap `make_tmp` armed. Do not arm a second trap here — it would
# replace that one and un-guard the PAT.
seed_log=""   # likewise
make_tmp seed_log
# REDIRECT AND `cat`, NEVER `| tee`. This line's exit status decides whether
# the setup claims completion, and a pipe puts a second process's status
# between the seed and that decision: under `pipefail` a `tee` that cannot
# write (a full disk, a scratch path that went away) reds a seed that
# succeeded, and under any frame that turned `pipefail` off it is the seed's
# own failure that disappears. `>` then `cat` gives the same transcript and
# the same file with `$?` meaning the seed. `test_pipefail_readers.sh` counts
# `| tee` as a census reader for exactly this.
seed_rc=0
DATABASE_NAME="${DATABASE_NAME}" uv run python manage.py zitadel_seed >"$seed_log" 2>&1 || seed_rc=$?
cat "$seed_log"
if [ "$seed_rc" = "0" ]; then
    # The OAuth door, armed from what the seed just resolved.
    #
    # `ZITADEL_MCP_AUDIENCE` empty does not mean "accept any audience", it means
    # the /mcp OAuth door is OFF (`apps/accounts/oauth.py`) — so every fresh
    # clone shipped with that door shut until a human read .env.example and
    # pasted an id by hand. The id is not a secret and is not a choice: it is
    # the project the line above either created or found, and Zitadel puts it
    # in every access token's `aud` for this project. The one thing this script
    # cannot know is whether an operator is pointing at an externally-managed
    # Zitadel with an audience of their own, which is what the
    # already-set branch below is for.
    #
    # Read off the seed's own `created`/`exists  project <name>  (<id>)` line
    # rather than asked for again, because a second lookup is a second answer:
    # what belongs in .env is the id the run that just configured this instance
    # actually used.
    #
    # Pinned to the verb as well as the noun, and to the FIRST such line: the
    # command prints that line early and prints prose afterwards, and prose
    # that happened to put "project" in its second word would otherwise hand
    # this an English word to write into .env.
    project_id="$(awk '
        $1 ~ /^(created|exists)$/ && $2 == "project" && id == "" { id = $NF }
        END { gsub(/[()]/, "", id); print id }
    ' "$seed_log")"
    if [ -z "${project_id}" ]; then
        echo "could not read the project id from zitadel_seed's output;" >&2
        echo "set ZITADEL_MCP_AUDIENCE in .env by hand (see .env.example)." >&2
    elif grep -q "^ZITADEL_MCP_AUDIENCE=." .env; then
        echo "ZITADEL_MCP_AUDIENCE already set in .env; leaving it alone"
    else
        env_set ZITADEL_MCP_AUDIENCE "${project_id}"
        echo "ZITADEL_MCP_AUDIENCE written to .env (${project_id})"
    fi
else
    echo "zitadel_seed did not complete; the rest of the stack is fine." >&2
    echo "Fix the PAT above and run: uv run python manage.py zitadel_seed" >&2
    SETUP_INCOMPLETE="zitadel_seed did not complete, so identity configuration was not applied"
fi
rm -f "$seed_log"

step "object storage bucket for this worktree"
# THE SAME PROBLEM AS THE DATABASE, AND THE SAME ANSWER. Agents build in
# parallel worktrees against ONE compose
# MinIO. Two checkouts writing `t/<tenant>/` into one bucket would see each
# other's objects, and a prefix delete in one would take the other's away — so
# the bucket follows the CHECKOUT, named for the SHA-256 of its own absolute
# path exactly as `DATABASE_NAME` is, and a name already in `.env` wins exactly
# as `DATABASE_NAME`'s does.
#
# THE DERIVATION IS NOT MIRRORED HERE, and that is the whole shape of this step.
# `db.sh` re-implements its hash in shell because it must work before `uv sync`
# has run; this one runs after it, so it can ASK the seam that owns the answer
# (`apps/files/storage.py::derived_bucket_name`) instead of keeping a second
# copy of the arithmetic in a second language for the two to drift apart in.
# `manage.py ensure_bucket` prints the name on stdout and nothing else, for
# exactly this line to capture; it also CREATES the bucket if it is absent,
# which is the other half — a name in `.env` pointing at no bucket makes
# /readyz report `storage: false`, which is a worse lie than reporting nothing.
#
# WHAT IT UNLOCKS, so nobody has to guess why this step exists: naming a bucket
# is the whole switch to S3 (`config/settings/base.py`), so after this line
# `/readyz` grows a `storage` member (`apps/core/health.py::checks` adds it only
# when a bucket is named) and `apps/files` can store, sign and stream for real
# on a laptop. Before it, every one of those was configured-as-absent.
#
# NOT FATAL, AND NOT SILENT (the same shape as at the seed above): a laptop
# whose MinIO is not up should still finish setup with a database, migrations
# and hooks. The failure is named on stderr, joins the verdict rather than
# replacing it — `${SETUP_INCOMPLETE:+…; }` appends, so identity's failure and
# this one can both be true — and the script exits non-zero at the end.
if bucket_name="$(DATABASE_NAME="${DATABASE_NAME}" uv run python manage.py ensure_bucket)"; then
    env_set AWS_STORAGE_BUCKET_NAME "${bucket_name}"
    echo "AWS_STORAGE_BUCKET_NAME=${bucket_name}"
else
    echo "no object storage: the bucket could not be made, so AWS_STORAGE_BUCKET_NAME" >&2
    echo "  was left alone. /readyz will carry no \`storage\` member and apps/files" >&2
    echo "  will refuse. Bring MinIO up and run: uv run python manage.py ensure_bucket" >&2
    SETUP_INCOMPLETE="${SETUP_INCOMPLETE:+${SETUP_INCOMPLETE}; }the object storage bucket was not made, so this checkout has no object storage"
fi

step "integrations"
# THE CENSUS, AT MINUTE ONE — the first of its four surfaces (INTEG-1).
#
# Everything above this line configured ONE thing each and said so in its own
# words; this says what the whole deployment now talks to, in one place, in the
# same words `manage.py integrations`, `deploy/release.sh`'s wall and the
# standing prober use. A person's first hour used to be spent discovering, one
# refusal at a time, which slots were filled by something real and which by a
# stand-in that succeeds quietly — the SMS transport being the worst of them
# (a fresh clone keeps `FakeSmsChannel` and nothing anywhere says so).
#
# NOT FATAL, AND NOT SILENT, exactly as the two steps above are: a fresh clone
# is SUPPOSED to be standing on some fakes, and a setup script that failed
# because the console mail backend is set would be crying wolf on every first
# run. So the report is printed and the exit status is not consulted — the
# refusing surface is the DEPLOY (`release.sh --wall`), where a fake is a
# genuine finding and where refusing costs nobody a first afternoon.
#
# `|| true` because `--wall` is deliberately absent here and the plain command
# still exits 2 if a seam could not be read; that is a finding for the report to
# carry rather than a reason to stop a laptop's setup.
DATABASE_NAME="${DATABASE_NAME}" uv run python manage.py integrations || true

step "git hooks"
if [ -d scripts/githooks ]; then
    git config core.hooksPath scripts/githooks
    chmod +x scripts/githooks/* 2>/dev/null || true
    echo "core.hooksPath set to scripts/githooks"
else
    echo "scripts/githooks does not exist yet; skipping hook wiring"
fi
# The last step's wall, closed HERE rather than by `setup_total` below, so it
# prints beside its own banner instead of underneath the guidance block.
step_end

# The verdict. Two banners and two exit codes, because "what this machine now
# has" is the one thing this script is asked, and there is no honest way to
# answer it with a single sentence that fits both outcomes. The guidance below
# is printed either way — it is still what to do next — but the FIRST line and
# `$?` agree with each other, which is what a skimming human and a CI runner
# each read.
if [ -n "${SETUP_INCOMPLETE}" ]; then
    cat <<INCOMPLETE >&2

Setup did NOT complete: ${SETUP_INCOMPLETE}
This worktree uses database ${DATABASE_NAME}; the database, the migrations and
the stack are fine, and the identity door is shut — /mcp's OAuth paths and
anything that needs a Zitadel project will not work until the seed succeeds.

  uv run python manage.py zitadel_seed     # after fixing ZITADEL_PAT in .env
INCOMPLETE
fi

cat <<NEXT

$(if [ -n "${SETUP_INCOMPLETE}" ]; then
    printf 'The rest of setup ran. This worktree uses database %s.' "${DATABASE_NAME}"
else
    printf 'Setup complete. This worktree uses database %s.' "${DATABASE_NAME}"
fi)

Next:
  source scripts/db.sh                     # export DATABASE_NAME in your shell
  uv run python manage.py zitadel_first_admin --email you@yourcompany.com
                                           # the deployment's first human, and BEFORE seed:
                                           # it refuses once a tenant exists. It prints the
                                           # link where that person sets their own password
                                           # at the identity platform. createsuperuser still
                                           # exists and is still the wrong road: no door here
                                           # authenticates by password, so the one it sets
                                           # opens nothing (ADR ident-4).
  uv run python manage.py grant_staff --email you@yourcompany.com
                                           # once they have signed in once: the one audited
                                           # road to is_staff, which is what opens /admin/.
  uv run python manage.py seed             # a tenant, an owner, a member, an API token —
                                           # a drivable clone, if you are not standing a
                                           # real deployment up
  uv run python manage.py issue_token --email you@example.com --name laptop --scope '*'
                                           # --scope is required; '*' means no limit.
                                           # Narrow it with --scope widgets:read (repeat per scope).
  ./scripts/serve.sh                       # http://127.0.0.1:8000/api/v1/docs
  ./scripts/worker.sh                      # the Temporal worker, in another shell
  ./scripts/test.sh                        # the test suite

  Temporal's web UI is on http://127.0.0.1:8233
  Zitadel is on http://localhost:8081 — console /ui/console, discovery
  /.well-known/openid-configuration. Sign in as ${ZITADEL_ADMIN_USERNAME:-zitadel-admin@djangobootstrap.localhost}
  with the password in .env. Identity CONFIGURATION goes through our services,
  never through that console.
NEXT

setup_total

# Exit 1, not 2: this script looked, and what it found is wrong (the header at
# the seed step). Last statement in the file, so a failure anywhere above still
# reaches here through `set -e` with its own status rather than this one.
[ -z "${SETUP_INCOMPLETE}" ] || exit 1
