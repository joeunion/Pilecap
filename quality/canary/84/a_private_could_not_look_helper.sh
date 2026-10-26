#!/usr/bin/env bash
# Planted: a private could-not-look helper beside the road; a here-string is not a heredoc.
set -euo pipefail

zzz_refuse() {
    read -r first <<< "$1"
    echo "!! zzz: could not look — $first" >&2
    exit 2
}
