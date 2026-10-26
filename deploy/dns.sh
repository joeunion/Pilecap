#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/../scripts/bash_only.sh" || exit 2
# Route 53, for the names this deployment answers on (ADR deploy-2).
#
#   deploy/dns.sh upsert <env> <ip>       the three A records for an environment
#   deploy/dns.sh delete <env> <ip>       remove them
#   deploy/dns.sh plant <file>            apply a batch of records from a file
#   deploy/dns.sh show                    what the zone holds today
#
# ONE ZONE, AND EVERY RECORD IN IT IS OWNED BY EXACTLY ONE PIECE OF WORK.
# Nobody writes DNS by hand. This script is what "creates" means, so that "who
# changed the record" has an answer that is not "somebody, in the console, in
# March".
#
# THE ZONE ID IS CONFIGURATION AND HAS NO DEFAULT. A deployment's hosted zone
# is the one thing this script cannot guess and must never guess: a wrong id is
# not an error, it is a correct-looking write into somebody else's zone. So
# `DJB_ZONE_ID` is REQUIRED and unset is a refusal, the same way `aws` missing
# from PATH is a refusal — never a fallback.
#
# THE DOMAIN IS CONFIGURATION WITH A DELIBERATELY UNRESOLVABLE DEFAULT.
# `DJB_DOMAIN` unset yields `example.invalid` — `.invalid` is reserved by
# RFC 2606 and can never resolve anywhere — because a placeholder that fails
# loudly on the first lookup is safer than a placeholder that resolves to
# somebody's real host. The zone-id refusal above means the unconfigured
# default can never reach a real zone on its own.

set -euo pipefail
set +x

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# `die` and `say` are deploy/lib.sh's.
DEPLOY_NAME=dns
# shellcheck source=deploy/lib.sh
. "$HERE/lib.sh" || exit 2

ZONE_ID="${DJB_ZONE_ID:-}"
[ -n "$ZONE_ID" ] || die "DJB_ZONE_ID is required — this deployment's Route 53 hosted zone id. There is no default: a guessed zone is a write into somebody else's DNS. 'aws route53 list-hosted-zones' names yours."
DOMAIN="${DJB_DOMAIN:-example.invalid}"
# 60 seconds. Short, deliberately: these records point at one box, and the
# moment somebody actually needs to change one is the moment a box has failed.
# A day of caching is a day of downtime, and the query cost of a 60s TTL on
# three records is measured in cents.
TTL="${DJB_DNS_TTL:-60}"

command -v aws >/dev/null 2>&1 || die "no 'aws' on PATH"

# The three names an environment answers on. Derived from the environment name,
# not listed per environment, so `prod` needs no edit here.
names_for() {
    local environment="$1"
    echo "$environment.$DOMAIN"
    echo "auth.$environment.$DOMAIN"
    echo "o11y.$environment.$DOMAIN"
}

change_batch() {
    # ACTION NAME TYPE VALUE... -> the JSON Route 53 wants, on stdout.
    local action="$1" name="$2" type="$3" value="$4"
    cat <<JSON
{"Changes":[{"Action":"$action","ResourceRecordSet":{
  "Name":"$name","Type":"$type","TTL":$TTL,
  "ResourceRecords":[{"Value":"$value"}]}}]}
JSON
}

case "${1:-}" in
    upsert|delete)
        ACTION="$(echo "${1}" | tr '[:lower:]' '[:upper:]')"
        ENVIRONMENT="${2:-}"
        IP="${3:-}"
        [ -n "$ENVIRONMENT" ] && [ -n "$IP" ] || die "usage: dns.sh $1 <env> <ip>"
        # DELETE requires the record's exact current value, which is why the ip
        # is an argument on both paths rather than only on upsert. Route 53
        # refuses a delete that does not match, which is the behaviour we want:
        # a stale ip in this command deletes nothing rather than the wrong thing.
        while read -r NAME; do
            say "$ACTION A $NAME -> $IP (ttl ${TTL}s)"
            aws route53 change-resource-record-sets \
                --hosted-zone-id "$ZONE_ID" \
                --change-batch "$(change_batch "$ACTION" "$NAME" A "$IP")" \
                --query 'ChangeInfo.Id' --output text
        done < <(names_for "$ENVIRONMENT")
        say "submitted. Propagation is Route 53's clock, not ours; 'dns.sh show' reads the zone back."
        ;;

    plant)
        # Records this script's `upsert` shape cannot express: a CNAME set, an
        # MX, a TXT — domain verification for an email provider, a DMARC
        # policy, anything a vendor hands you as a table.
        #
        # **P4 plants none of these** (Amendment A2: E1 is re-cut as Resend
        # through anymail, with no external DNS clock, and V1-6 is struck).
        # The subcommand stays because the next environment that needs a
        # provider's verification records should have one place to put them,
        # rather than a console session nobody can replay.
        #
        # A FILE RATHER THAN ARGUMENTS, because a verification record is a
        # long opaque string and retyping one is a verification that silently
        # never completes. The file is Route 53's own change-batch JSON:
        # whatever the provider gave you, written down.
        FILE="${2:-}"
        [ -f "$FILE" ] || die "usage: dns.sh plant <change-batch.json>"
        say "applying $FILE to zone $ZONE_ID"
        aws route53 change-resource-record-sets \
            --hosted-zone-id "$ZONE_ID" \
            --change-batch "file://$FILE" \
            --query 'ChangeInfo.Id' --output text
        ;;

    show)
        # The whole zone, so a runbook step can paste the census rather than
        # assert one. Everything here is public information by construction —
        # DNS is a public database — so this is the one place in deploy/ where
        # printing what was found is not a leak.
        aws route53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
            --query 'ResourceRecordSets[].{Name:Name,Type:Type,TTL:TTL,Value:ResourceRecords[0].Value}' \
            --output table
        ;;

    *)
        die "usage: dns.sh <upsert|delete> <env> <ip> | dns.sh plant <file> | dns.sh show"
        ;;
esac
