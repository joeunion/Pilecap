#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/../scripts/bash_only.sh" || exit 2
# Scan one image for known vulnerabilities with trivy, folded into 0/1/2.
#
#   deploy/image_scan.sh <oci-archive.tar | image-ref> [--report-only] [--sbom <file>] [--report <file>]
#   deploy/image_scan.sh --install <dir>     put the pinned trivy in <dir>, its checksum verified
#
# Exit 0 clean, or findings below the bar · 1 a CRITICAL with a fix available (or a bad or
# expired exception) · 2 could not look: no scanner, no database, an unreadable image or report.
# `--report-only` prints a blocking finding and exits 0; a could-not-look is still 2.
# `--sbom` writes the image's CycloneDX SBOM; `--report` keeps trivy's JSON report.
# The judgment and the exceptions are `deploy/image_scan_policy.py`'s; this file runs the scanner.
# An archive is scanned for its first platform (linux/amd64); a ref is read from its registry.
# does-not-cover: an archive's second platform — the first (linux/amd64) is the one scanned.
# does-not-cover: the vulnerability database's freshness — a stale database answers clean.
# does-not-cover: a vulnerability with no fixed version — printed, never blocking.

set -euo pipefail
set +x

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_NAME=image_scan
DEPLOY_NOTHING="Nothing was judged."
# shellcheck source=deploy/lib.sh
. "$HERE/lib.sh" || exit 2

#: The one pin of the scanner: its version and each release asset's published SHA-256.
TRIVY_VERSION=0.75.0
TRIVY_SHA256_Linux_64bit=c6e65abddb348e25f10549df887045629cf28cc72453cd1c63acb717316b3f3f
TRIVY_SHA256_macOS_ARM64=4a77108cccf8e55c8d6823e1e759939a622277e66cd0daa3c1fc621ed69e4568

install_trivy() {
    local dir="$1" asset want got work
    case "$(uname -s)/$(uname -m)" in
    Linux/x86_64) asset=Linux-64bit want=$TRIVY_SHA256_Linux_64bit ;;
    Darwin/arm64) asset=macOS-ARM64 want=$TRIVY_SHA256_macOS_ARM64 ;;
    *) die "no pinned trivy asset for $(uname -s)/$(uname -m)" ;;
    esac
    command -v curl >/dev/null || die "no curl on PATH — the scanner cannot be fetched"
    mkdir -p "$dir"
    work="$(mktemp -d)"
    curl -fsSL --retry 3 -o "$work/trivy.tar.gz" \
        "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_${asset}.tar.gz" ||
        die "the trivy ${TRIVY_VERSION} download failed"
    got="$(sha256_of "$work/trivy.tar.gz")" || die "the download's SHA-256 could not be computed"
    [ "$got" = "$want" ] || die "trivy ${TRIVY_VERSION} ${asset} is ${got}, not the pinned ${want}"
    tar -xzf "$work/trivy.tar.gz" -C "$dir" trivy
    rm -rf "$work"
    say "trivy ${TRIVY_VERSION} (${asset}, sha256 ${want}) in ${dir}"
}

if [ "${1:-}" = "--install" ]; then
    [ "$#" = 2 ] || usage
    install_trivy "$2"
    exit 0
fi

target="" sbom="" keep="" report_only=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    --report-only) report_only=--report-only ;;
    --sbom) sbom="${2:?--sbom takes a file}" && shift ;;
    --report) keep="${2:?--report takes a file}" && shift ;;
    --help | -h) usage 0 ;;
    -*) die "unknown flag '$1'" ;;
    *)
        [ -z "$target" ] || die "one image per run; '$target' and '$1' were both given"
        target="$1"
        ;;
    esac
    shift
done
[ -n "$target" ] || usage

command -v trivy >/dev/null || die "no trivy on PATH — '$0 --install <dir>' fetches the pinned ${TRIVY_VERSION}"
command -v python3 >/dev/null || die "no python3 on PATH — the policy cannot judge the report"

work="$(mktemp -d)"
# bash 3.2 exits with the trap's status, so the trap hands back the one it was given.
trap 'status=$?; rm -rf "$work"; exit "$status"' EXIT

if [ -f "$target" ]; then
    image="$(basename -- "$target" .tar)"
    mkdir "$work/layout"
    tar -xf "$target" -C "$work/layout" || die "$target could not be unpacked"
    [ -f "$work/layout/index.json" ] || die "$target is not an OCI archive (no index.json)"
    source_args=(--input "$work/layout")
else
    image="${target%%@*}"
    image="${image%:*}"
    image="${image##*/}"
    source_args=(--image-src remote "$target")
fi

report="$work/report.json"
if ! trivy image --quiet --no-progress --skip-version-check --scanners vuln --list-all-pkgs \
    --format json --output "$report" "${source_args[@]}" 2>"$work/stderr"; then
    die "trivy could not scan $target" "$(tail -n 5 "$work/stderr")"
fi
[ -z "$keep" ] || cp "$report" "$keep"
if [ -n "$sbom" ]; then
    trivy convert --quiet --format cyclonedx --output "$sbom" "$report" 2>"$work/stderr" ||
        die "trivy could not write the SBOM for $target" "$(tail -n 5 "$work/stderr")"
    say "$image: SBOM $sbom"
fi

status=0
if [ -n "$report_only" ]; then
    python3 "$HERE/image_scan_policy.py" "$report" "$image" --report-only || status=$?
else
    python3 "$HERE/image_scan_policy.py" "$report" "$image" || status=$?
fi
case "$status" in
0) exit 0 ;;
1) gate_finding "image_scan: $image carries a CRITICAL with a fix — deploy/image_scan_policy.py names the way out" ;;
*) die "the policy could not judge the report for $target (exit $status)" ;;
esac
