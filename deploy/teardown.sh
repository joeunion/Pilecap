#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/../scripts/bash_only.sh" || exit 2
# The other half of provision.sh, and a first-class one (ADR deploy-1:
# teardown-friendly; the environments contract: prod is EPHEMERAL, provisioned
# by the runbook for R1 and torn down after evidence).
#
#   deploy/teardown.sh local                     stop the laptop stack, keep the data
#   deploy/teardown.sh local --purge             ...and remove its volumes and env file
#   deploy/teardown.sh --all-mine                EVERY project this checkout brought up,
#                                                with its volumes — the reaper (N112c)
#   deploy/teardown.sh <env> --confirm           destroy the environment's AWS resources
#
# WHY THIS IS A SCRIPT AND NOT A PARAGRAPH IN THE RUNBOOK. An environment
# nobody can delete in one command is an environment that stays up, and a
# monthly bill is the least of it: the prod twin exists to be created from the
# runbook, proved, and removed, and a teardown performed by hand leaves an
# orphan security group and a $2/mo volume every single time. The list of what
# to delete also has to be the list of what was created, which is why the two
# scripts are neighbours and name the same things.
#
# IT REFUSES BY DEFAULT. `--confirm` for anything that destroys a cloud
# resource, `--purge` for anything that destroys local data. The RDS final
# snapshot is TAKEN, not skipped: a teardown is when somebody discovers they
# wanted one row.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
set +x

# `die` and `say` are deploy/lib.sh's.
DEPLOY_NAME=teardown
# shellcheck source=deploy/lib.sh
. "$HERE/lib.sh" || exit 2

ENVIRONMENT="${1:-}"
FLAG="${2:-}"
[ -n "$ENVIRONMENT" ] || die "usage: teardown.sh <local|--all-mine|staging|prod> [--confirm|--purge]"

# --- WHOSE STACK AM I ABOUT TO DESTROY --------------------------------------
# `kill_mine.sh`'s refusal, in compose's vocabulary. That script exists because
# `pkill -f <name>` killed a peer worktree's worker: a NAME cannot tell your
# process from somebody else's. `docker compose down` against a shared project
# name is the same mistake with volumes attached — and it was live here, because
# `compose.yaml` pinned one project name for every checkout on the machine.
#
# So ownership is not decided by a name. It is decided by two facts:
#
#   1. the project name this CHECKOUT derives (deploy/provision.sh
#      derived-project-name — which is a DIFFERENT question from `project-name`,
#      and this file is the reason the two are separate subcommands: fold the
#      adoption into the derivation and the comparison below compares a value
#      with itself and always agrees, which is a destructive command whose
#      ownership check has quietly stopped asking anything),
#      which no other checkout can produce, and
#   2. failing that, the `com.docker.compose.project.working_dir` label Docker
#      itself wrote on the running containers — which says which directory
#      brought the stack up, and cannot be argued with.
#
# A project that matches (1) is mine. A project that matches (2) is mine too:
# that is a deliberately-named second stack from this checkout — B1's restore
# drill — and refusing it would make the override useless. Anything else is
# somebody's, and it is not mine to `down`.
# How many containers this project has on this machine, in any state. Asked
# SEPARATELY from the label below, and that separation is the whole point: an
# empty label has two causes — "no containers" and "the query is broken" — and a
# function that returned "" for both would report a broken check as a clean
# absence. Counting first makes them different answers.
project_container_count() {
    docker ps -aq --filter "label=com.docker.compose.project=$1" 2>/dev/null | grep -c . || true
}

# Which directory brought this project up, from the label Docker itself wrote.
#
# `{{.Label "key"}}`, NOT `{{index .Labels "key"}}`. In `docker ps --format`,
# `.Labels` is a comma-joined STRING, not a map: `index` on it raises
# "cannot index slice/array with type string", docker exits 1, and the template
# prints nothing. Shipped that way once — with a `|| true` in front of it, which
# turned the template error into a silent "" and made this check pass by being
# broken. Verified against Docker 28.0.1 that `.Label` returns the path and
# agrees with `docker inspect`'s `index .Config.Labels`.
#
# The `|| true` stays, because `docker ps --format` also exits 1 when nothing
# matches the filter and `set -o pipefail` would kill this script before it
# could say why. It is safe now only because the caller has already counted.
project_working_dir() {
    local found
    found="$(docker ps -a --filter "label=com.docker.compose.project=$1" \
        --format '{{.Label "com.docker.compose.project.working_dir"}}' 2>/dev/null \
        | sed -n '1p')" || true
    printf '%s' "$found"
}

resolve_project() {
    # Precedence, matching compose's own and verified against v2.33: an exported
    # COMPOSE_PROJECT_NAME wins, then the line provision.sh wrote into
    # deploy/.env, then this checkout's derivation. Nothing here reads a `name:`
    # out of compose.yaml, because there is deliberately no longer one there.
    if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then
        printf '%s' "$COMPOSE_PROJECT_NAME"
        return
    fi
    if [ -f "$HERE/.env" ]; then
        local from_file
        # deploy/envfile.py is the file's one reader (the same one provision.sh
        # asks), so a double-quoted or `export`ed line reads here as it does there.
        from_file="$("${PYTHON_BIN:-python3}" "$HERE/envfile.py" get "$HERE/.env" COMPOSE_PROJECT_NAME)"
        if [ -n "$from_file" ]; then
            printf '%s' "$from_file"
            return
        fi
    fi
    # `derived-project-name`, not `project-name`: the two lines above ARE the
    # first two rungs of `project-name`'s own precedence ladder, so
    # asking it here would ask the same two questions twice and then answer
    # with the third. The third is what is wanted, by its own name.
    "$HERE/provision.sh" derived-project-name
}

# --- --all-mine: the reaper --------------------------------------------------
# N112c, and it is a SECOND-STRIKE fix rather than a convenience. The machine
# filled up: three laptop deploy stacks, each with its own ClickStack volume, its
# own Postgres volume and its own Caddy data, left behind by rungs that tore down
# "their" stack and did not know about the second one they had named by hand for a
# drill. `teardown.sh local` destroys ONE project; nothing destroyed the set.
#
# THE POPULATION IS DERIVED, NEVER TYPED, and it is derived from the same fact
# `provision.sh up` reads: Docker's own record of which config file brought a
# project up. A project whose `com.docker.compose.project.config_files` (or, for
# a stopped one, the working-directory label the rest of this file already
# trusts) names THIS checkout's `deploy/compose.yaml` is this checkout's. No
# other checkout can produce that string, and a name is still not a licence.
#
# It takes `--volumes` unconditionally, and that is the whole point of it: the
# thing that filled the disk was volumes, and a reaper that leaves them is a
# reaper that does not reap. The refusal it inherits is stronger than `local`'s,
# not weaker: it never touches a project it cannot prove came from here.
#
# THE ORDER OF THE TWO SWEEPS IS LOAD-BEARING. It runs the per-project
# `down` FIRST and the derived-name orphan sweep AFTER, because those are the
# only two orders and the other one is broken in both halves at once:
#
#   * MECHANICALLY. A volume a running container holds cannot be removed. With
#     the sweep first, on a LIVE stack every `docker volume rm` fails, `set -e`
#     kills the script at the first one, and NOTHING is torn down — no `down`,
#     no `.env` removal, no census AFTER. Reproduced live on an eleven-container
#     laptop stack.
#   * AS A SENTENCE. The sweep announces "volumes ... with no project left to
#     own them". Run before the `down`, it said that about a project that was
#     running at the time. A message that describes a state the instrument has
#     not reached yet is the same defect as a check that has stopped asking.
#
# The fix is the ordering and NOT an `|| true` on the `rm`. A tolerated failure
# on a destructive command is how an instrument reports a sweep it did not
# perform — the `.Label` class at line 73, which is exactly what made that check
# pass by being broken. So: after the `down`, a volume that still cannot be
# removed is a genuine finding. It is named, its holder is named where Docker
# can say, the rest of the reap still runs, and the script exits non-zero.
#
# EXIT STATUS OF `--all-mine`: 0 everything reaped · 1 the reap completed and a
# named volume survived it · 2 the census could not be read (`die`), which is a
# refusal to judge and not a report of an empty machine.
if [ "$ENVIRONMENT" = "--all-mine" ]; then
    command -v docker >/dev/null 2>&1 || die "no 'docker' on PATH"

    # A COUNT, not a flag, and it is why this block no longer aborts: the reap
    # does not stop at the first volume it cannot remove. Every failure is
    # printed as it happens, every remaining project is still torn down, and
    # this number decides the exit status at the bottom of the block.
    VOLUME_FAILURES=0
    VOLUMES_REMOVED=0
    # The names it has already failed on and already shouted about. A volume the
    # per-project sweep could not remove is found AGAIN by the derived-name sweep
    # below when the two populations overlap; saying so twice would make one
    # stuck volume read as two, which is the same lie in the other direction.
    VOLUMES_FAILED=""

    # WHO IS HOLDING IT, asked of Docker rather than inferred. An empty answer
    # is NOT "nobody": `--filter volume=` also comes back empty when the query
    # itself found nothing to say. The caller prints that distinction instead of
    # resolving it in the instrument's favour.
    volume_holders() {
        docker ps -a --filter "volume=$1" \
            --format '{{.Names}} ({{.State}})' 2>/dev/null | sed -n '1,5p' || true
    }

    # THE ONE DESTRUCTIVE CALL IN THIS BLOCK. Per volume, so a failure names the
    # volume rather than the batch; loud on stderr, because after the `down` a
    # volume that is still held is a finding somebody has to look at; and it
    # keeps going, because the alternative is an abort that leaves the
    # remaining projects, the `.env` and the census AFTER undone. It counts what
    # it actually removed so no caller can claim a removal it did not perform.
    remove_volumes_loudly() {
        local volume err holders
        for volume in "$@"; do
            case " $VOLUMES_FAILED " in
            *" $volume "*)
                # Said once, on stderr, above — and said here too, because a
                # list printed with nothing said about one of its entries is a
                # reader's blank the count at the end has to fill.
                say "  $volume — already reported above; not retried"
                continue
                ;;
            esac
            if err="$(docker volume rm "$volume" 2>&1 >/dev/null)"; then
                VOLUMES_REMOVED=$((VOLUMES_REMOVED + 1))
                continue
            fi
            VOLUME_FAILURES=$((VOLUME_FAILURES + 1))
            VOLUMES_FAILED="$VOLUMES_FAILED $volume"
            holders="$(volume_holders "$volume")"
            {
                echo "!! teardown: volume NOT removed: $volume"
                if [ -n "$err" ]; then
                    printf '   docker      %s\n' "$err"
                fi
                if [ -n "$holders" ]; then
                    printf '   held by     %s\n' "$holders"
                else
                    echo "   held by     Docker named no container; who holds it is unknown"
                fi
            } >&2
        done
    }

    # `-a`: stopped projects too. A stopped stack's volumes are exactly as large
    # as a running one's, and "it is not running" is the reason nobody noticed
    # the last three.
    # The payload travels as an ARGUMENT, not on stdin, because stdin is already
    # spoken for: `python -` reads the program there. A pipe AND a heredoc into
    # one command is a program that reads its own source as data — which is
    # exactly what this did on its first run, and it reported "could not read
    # docker compose ls" about a docker that had answered perfectly. Project
    # names and file paths are not secrets, so `ps` is not an argument here.
    MINE="$("${PYTHON_BIN:-python3}" - "$HERE/compose.yaml" \
             "$(docker compose ls -a --format json 2>/dev/null)" <<'PYTHON'
import json, sys

wanted, payload = sys.argv[1], sys.argv[2]
try:
    projects = json.loads(payload)
except Exception:
    # A docker that could not answer is NOT "no projects". Exit 2 rather than
    # report an empty census: not clearing anything is not the same as having
    # nothing to clear.
    raise SystemExit(2)
for project in projects:
    files = str(project.get("ConfigFiles", "")).split(",")
    if any(entry.strip() == wanted for entry in files):
        print(project.get("Name", ""))
PYTHON
    )" || die "could not read 'docker compose ls'. Nothing was stopped and nothing was removed."

    say "census BEFORE:"
    docker compose ls -a
    echo ""

    # --- THE PROJECTS FIRST -------------------------------------------------
    # Before the volume sweep below, and see the ORDERING paragraph in this
    # block's header for why that is not a matter of taste.
    if [ -z "$MINE" ]; then
        say "no compose project on this machine names $HERE/compose.yaml."
    else
        say "projects this checkout brought up:"
        # shellcheck disable=SC2086
        printf '  %s\n' $MINE

        for PROJECT in $MINE; do
            say "down --volumes: $PROJECT"
            # `--profile laptop` so the laptop-only `db` service is in scope for
            # the `down`; on a box the profile matches nothing and changes
            # nothing.
            docker compose -p "$PROJECT" -f "$HERE/compose.yaml" --profile laptop \
                down --volumes --remove-orphans

            # --- AND THE VOLUMES THAT `down` CANNOT SEE -----------------------
            # `down --volumes` removes the volumes declared in the compose files
            # it was GIVEN, and this one is given `compose.yaml` alone. A stack
            # brought up with an override that declares its own volume — the
            # laptop's `observability/alerts/compose.sink.yaml` and its
            # `alerts_dummy_log` is the worked example — leaves that volume
            # behind, and a reaper that leaves volumes is the thing this flag
            # exists to stop. Measured: 15 volumes before, 1 after, and the
            # survivor was exactly that one.
            #
            # Reconstructing the override list is not possible here (`docker
            # compose ls` reports the files, but a file that has since been
            # deleted or renamed would break the `down`), so the sweep works off
            # Docker's own project label instead. `<project>_<volume>` is
            # compose's naming rule, and `label=com.docker.compose.project` is
            # the same fact the census above is derived from — so this removes
            # what THIS project owns and cannot reach another one's, whatever it
            # is called.
            LEFTOVER="$(docker volume ls -q \
                --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null || true)"
            if [ -n "$LEFTOVER" ]; then
                # shellcheck disable=SC2086
                say "  and $(printf '%s\n' $LEFTOVER | grep -c .) volume(s) no override file was passed for:"
                # shellcheck disable=SC2086
                printf '    %s\n' $LEFTOVER
                # shellcheck disable=SC2086
                remove_volumes_loudly $LEFTOVER
            fi
        done
    fi

    # --- AND THE VOLUMES OF A PROJECT THAT IS NO LONGER A PROJECT -----------
    # `docker compose ls -a` lists projects, and a project stops existing the
    # moment its last container is removed — but its VOLUMES do not. So a stack
    # taken down with `down` (no `--volumes`) leaves a full set behind that this
    # reaper then reports as "nothing to reap", which is the exact sentence that
    # lets a 16-era db_data survive into a PG-18 boot and cost a debugging
    # round. Volumes are the thing that fills the disk; a
    # reaper that only sees registered projects cannot be the answer to that.
    #
    # IT RUNS HERE, after every project above is down, and that placement is
    # what makes its own sentence true: at this point there really is no project
    # left to own what it finds.
    #
    # Matched on the DERIVED project name, because that is the only one
    # reconstructible without a project to ask: `com.docker.compose.project`
    # is on every volume compose creates. `derived-project-name` and NOT
    # `project-name`: the resolved name folds in `COMPOSE_PROJECT_NAME` and the
    # adopted line in `deploy/.env`, and matching a destructive sweep on a name
    # somebody else could have exported is exactly the widening to avoid.
    # DECLARED LIMIT: a stack somebody
    # named by hand (`-p djb-drill`) and then removed the containers of is NOT
    # reachable here — its name is not derivable from anything on disk. Name it
    # yourself: `docker volume ls --filter label=com.docker.compose.project=<name>`.
    ORPHANED="$(docker volume ls -q \
        --filter "label=com.docker.compose.project=$("$HERE/provision.sh" derived-project-name)" 2>/dev/null || true)"
    if [ -n "$ORPHANED" ]; then
        say "volumes from this checkout's derived project with no project left to own them:"
        # shellcheck disable=SC2086
        printf '  %s\n' $ORPHANED
        REMOVED_BEFORE_SWEEP="$VOLUMES_REMOVED"
        # shellcheck disable=SC2086
        remove_volumes_loudly $ORPHANED
        say "removed $((VOLUMES_REMOVED - REMOVED_BEFORE_SWEEP)) orphaned volume(s)"
    fi

    if [ -z "$MINE" ] && [ -z "$ORPHANED" ]; then
        say "nothing else to reap."
    fi

    # The generated env file goes with them: it is this checkout's, mode 600, and
    # `provision.sh env-file` writes a fresh one in one command. Reported as what
    # happened, not as what was attempted.
    if [ -f "$HERE/.env" ]; then
        rm -f "$HERE/.env"
        say "removed $HERE/.env"
    else
        say "no $HERE/.env to remove"
    fi

    echo ""
    say "census AFTER:"
    docker compose ls -a

    # The reap RAN — everything above happened — and something survived it. That
    # is not a tolerated failure and it is not enforcement breaking either: it is
    # a finding, and it leaves by the door findings leave by.
    if [ "$VOLUME_FAILURES" -gt 0 ]; then
        echo "" >&2
        echo "!! teardown: $VOLUME_FAILURES volume(s) survived this reap, named above." >&2
        echo "   Their project was taken down and they are still held, so something" >&2
        echo "   outside the projects this checkout brought up is holding them." >&2
        echo "   Everything else in the reap was completed." >&2
        exit 1
    fi
    exit 0
fi

if [ "$ENVIRONMENT" = "local" ]; then
    DERIVED="$("$HERE/provision.sh" derived-project-name)"
    PROJECT="$(resolve_project)"
    CHECKOUT="$( cd "$HERE" && git rev-parse --show-toplevel 2>/dev/null || dirname "$HERE" )"

    if [ "$PROJECT" = "$DERIVED" ]; then
        say "project $PROJECT (this checkout's own)"
    else
        CONTAINERS="$(project_container_count "$PROJECT")"
        WORKING_DIR="$(project_working_dir "$PROJECT")"

        if [ "$CONTAINERS" -gt 0 ] && [ -z "$WORKING_DIR" ]; then
            # Containers exist and the label query answered nothing. That is not
            # "no owner" — it is this check having stopped working, and the one
            # thing it may not do then is let a destructive command through.
            echo "!! teardown: ENFORCEMENT BROKEN." >&2
            echo "   project     $PROJECT" >&2
            echo "   containers  $CONTAINERS" >&2
            echo "" >&2
            echo "   Docker reports containers for that project but no" >&2
            echo "   com.docker.compose.project.working_dir label to read, so there" >&2
            echo "   is no way to say whose they are. Not clearing anything is not" >&2
            echo "   the same as clearing it. Nothing was stopped or removed." >&2
            exit 2
        fi

        if [ -z "$WORKING_DIR" ]; then
            echo "!! teardown: REFUSED." >&2
            echo "   project     $PROJECT" >&2
            echo "   derived     $DERIVED" >&2
            echo "   checkout    $CHECKOUT" >&2
            echo "" >&2
            echo "   That project name is not this checkout's, and it has no containers" >&2
            echo "   on this machine — so there is nothing to read a working directory" >&2
            echo "   off, and no way to prove it would be yours to destroy. A name is" >&2
            echo "   not a licence (scripts/kill_mine.sh, refusal 1). Nothing was" >&2
            echo "   stopped and nothing was removed." >&2
            exit 2
        fi
        if [ "$WORKING_DIR" != "$HERE" ]; then
            echo "!! teardown: REFUSED." >&2
            echo "   project     $PROJECT" >&2
            echo "   brought up from  $WORKING_DIR" >&2
            echo "   this checkout    $HERE" >&2
            echo "   derived name     $DERIVED" >&2
            echo "" >&2
            echo "   Docker's own label says another checkout owns those containers," >&2
            echo "   their network and their volumes. Tearing them down here would be" >&2
            echo "   the collision this refusal exists for. Run it from that checkout." >&2
            echo "   Nothing was stopped and nothing was removed." >&2
            exit 2
        fi
        say "project $PROJECT (named override; Docker's label says this checkout brought it up)"
    fi

    # --- the laptop ----------------------------------------------------------
    # `down` without `-v` first, always. Stopping is reversible; removing the
    # volumes takes Zitadel's bootstrap PAT, ClickStack's history and (on the
    # laptop profile) the whole database with it.
    #
    # `-p "$PROJECT"` on every call, explicitly, even though `deploy/.env` would
    # supply the same answer: the name this script CHECKED has to be the name it
    # acts on, or the check guarded a different stack from the one it destroyed.
    say "stopping the deploy stack"
    docker compose -p "$PROJECT" -f "$HERE/compose.yaml" --profile laptop down --remove-orphans

    if [ "$FLAG" = "--purge" ]; then
        say "removing volumes and the generated env file"
        docker compose -p "$PROJECT" -f "$HERE/compose.yaml" --profile laptop down --volumes --remove-orphans
        rm -f "$HERE/.env"
        say "purged. 'deploy/provision.sh env-file deploy/.env laptop' starts over."
    else
        say "volumes kept. Pass --purge to remove them and the generated env file."
    fi
    exit 0
fi

# --- an AWS environment ------------------------------------------------------
# THE NAMESPACE IS CONFIGURATION AND HAS NO DEFAULT, and it matters more here
# than anywhere else in this deployment: `provision.sh` under a guessed
# namespace CREATES things in somebody else's account; this script DELETES them.
# the grammar of `deploy/dns.sh`'s `DJB_ZONE_ID` refusal, and the refusal is before the summary because
# the summary is the list of what would be destroyed.
#
# The laptop branches above have already exited: `local` and `--all-mine`
# compose no AWS coordinate, so neither is held to this.
command -v aws >/dev/null 2>&1 || die "no 'aws' on PATH"
NAMESPACE="${DJB_DEPLOY_NAMESPACE:-}"
[ -n "$NAMESPACE" ] || die "DJB_DEPLOY_NAMESPACE is required — this deployment's namespace, the slug every resource this would destroy is named from. There is no default: a guessed namespace is a DELETE against somebody else's resources. It is a slot in this environment's env file (deploy/env.staging.example); on a box 'set -a; . deploy/.env; set +a' exports it."
REGION="${AWS_REGION:-us-east-1}"
NAME="${NAMESPACE}-$ENVIRONMENT"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)" \
    || die "cannot read the AWS account id — is the session live? Nothing was destroyed."
MEDIA="$(bucket_name media "$ENVIRONMENT" "$ACCOUNT")"
BACKUPS="$(bucket_name backups "$ENVIRONMENT" "$ACCOUNT")"

cat <<SUMMARY
teardown: about to DESTROY $NAME in $REGION

    EC2       instances tagged Name=$NAME (terminated)
    RDS       $NAME-db (final snapshot taken first)
    S3        s3://$MEDIA, s3://$BACKUPS  (emptied, then deleted)
    Secrets   ${NAMESPACE}/$ENVIRONMENT/env  (scheduled for deletion, 7-day window)
    SG        $NAME-web, $NAME-db
    DNS       NOT touched — deploy/dns.sh owns records; run it with 'delete'

Nothing here is recoverable except from the final snapshot and the 7-day
secret window.
SUMMARY

[ "$FLAG" = "--confirm" ] || die "refusing without --confirm"

# exists <what> <aws argv…> — 0 AWS answered that it stands · 1 AWS answered that it
# does not (a NotFound or a 404) · anything else is could-not-look: exit 2 with
# AWS's own lines, never a skip, because a skipped deletion is a resource left
# standing under a teardown that finished green (an SSO token expires mid-run).
exists() {
    local what=$1 err rc=0
    shift
    err="$("$@" 2>&1 >/dev/null)" || rc=$?
    [ "$rc" = "0" ] && return 0
    case "$err" in
    *NotFound* | *"(404)"*) return 1 ;;
    esac
    gate_die "teardown stopped here: what is above was deleted, what is below was not looked at." \
        "${DEPLOY_NAME}: COULD NOT LOOK — the probe for $what failed (exit $rc), so whether it stands is unknown." \
        "AWS said: ${err:-(nothing)}"
}

# Order matters and it is the reverse of creation: instances before the security
# group they reference, the bucket's objects before the bucket, the database
# before the group its rule names.
INSTANCES="$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text)"
if [ -n "$INSTANCES" ]; then
    say "terminating: $INSTANCES"
    # shellcheck disable=SC2086  # deliberate word splitting: a list of ids
    aws ec2 terminate-instances --region "$REGION" --instance-ids $INSTANCES >/dev/null
    # shellcheck disable=SC2086
    aws ec2 wait instance-terminated --region "$REGION" --instance-ids $INSTANCES
fi

if exists "RDS $NAME-db" aws rds describe-db-instances --region "$REGION" --db-instance-identifier "$NAME-db"; then
    SNAPSHOT="$NAME-final-$(date -u +%Y%m%d%H%M%S)"
    say "deleting RDS with final snapshot $SNAPSHOT"
    aws rds delete-db-instance --region "$REGION" \
        --db-instance-identifier "$NAME-db" \
        --final-db-snapshot-identifier "$SNAPSHOT" >/dev/null
    aws rds wait db-instance-deleted --region "$REGION" --db-instance-identifier "$NAME-db"
    say "final snapshot: $SNAPSHOT (it survives this teardown; delete it deliberately)"
fi

for BUCKET in "$MEDIA" "$BACKUPS"; do
    if exists "s3://$BUCKET" aws s3api head-bucket --bucket "$BUCKET"; then
        say "emptying and deleting s3://$BUCKET"
        # Versioned buckets keep every delete marker; `s3 rm --recursive`
        # leaves the versions behind and `delete-bucket` then fails with a
        # message about the bucket not being empty, which is true and unhelpful.
        aws s3api delete-objects --bucket "$BUCKET" --delete "$(aws s3api list-object-versions \
            --bucket "$BUCKET" --output json \
            --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}')" >/dev/null 2>&1 || true
        aws s3api delete-objects --bucket "$BUCKET" --delete "$(aws s3api list-object-versions \
            --bucket "$BUCKET" --output json \
            --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}')" >/dev/null 2>&1 || true
        aws s3api delete-bucket --bucket "$BUCKET" >/dev/null
    fi
done

if exists "the secret ${NAMESPACE}/$ENVIRONMENT/env" aws secretsmanager describe-secret --secret-id "${NAMESPACE}/$ENVIRONMENT/env"; then
    # 7 days, not `--force-delete-without-recovery`. A teardown that turns out
    # to have been premature is recoverable for a week; one that shredded the
    # Fernet key is not recoverable at all, and every tenant credential the key
    # protected goes with it.
    say "scheduling ${NAMESPACE}/$ENVIRONMENT/env for deletion (7-day recovery window)"
    aws secretsmanager delete-secret --secret-id "${NAMESPACE}/$ENVIRONMENT/env" \
        --recovery-window-in-days 7 >/dev/null
fi

# A network interface can outlive `instance-terminated` by seconds, so a
# DependencyViolation is retried a bounded few times; any other refusal is not.
delete_group() {
    local group=$1 id=$2 attempt=1 tries=6 err
    while ! err="$(aws ec2 delete-security-group --region "$REGION" --group-id "$id" 2>&1 >/dev/null)"; do
        case "$err" in
        *DependencyViolation*) ;;
        *) die "could not delete security group $group ($id): $err" ;;
        esac
        [ "$attempt" -lt "$tries" ] \
            || die "security group $group ($id) still refuses after $tries attempts: $err"
        say "security group $group ($id) still has a dependent object (attempt $attempt of $tries); retrying in 10s"
        sleep 10
        attempt=$((attempt + 1))
    done
}

# $NAME-db's ingress rule names $NAME-web as its source: the referencing group goes first.
PROBE_SAID="$(mktemp "${TMPDIR:-/tmp}/teardown-probe.XXXXXX")" || die "no scratch file for AWS's answer"
trap 'rm -f "$PROBE_SAID"' EXIT
for GROUP in "$NAME-db" "$NAME-web"; do
    ID="$(aws ec2 describe-security-groups --region "$REGION" \
        --filters "Name=group-name,Values=$GROUP" \
        --query 'SecurityGroups[0].GroupId' --output text 2>"$PROBE_SAID")" ||
        gate_die "teardown stopped here: what is above was deleted, $GROUP and what follows were not." \
            "${DEPLOY_NAME}: COULD NOT LOOK — the probe for security group $GROUP failed." \
            "AWS said: $(cat "$PROBE_SAID")"
    if [ "$ID" != "None" ] && [ -n "$ID" ]; then
        say "deleting security group $GROUP ($ID)"
        delete_group "$GROUP" "$ID"
    fi
done

say "done. DNS records are deploy/dns.sh's; the final RDS snapshot is kept on purpose."
