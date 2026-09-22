#!/usr/bin/env bash
# THE CONTROL FOR CLASS (b) FORM 1, byte-for-byte the same shape, one drawer
# over. A template-owned script may open a drawer all day long — that is the
# convention working — as long as the table says which reader opens it. The
# same file is a finding or it is nothing, and the difference is one row.
set -euo pipefail
for leg in scripts/local/legs/*.sh; do
    [ -x "$leg" ] || continue
    "$leg"
done
