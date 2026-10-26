#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
# seam_check.sh [--root DIR] [--settings MODULE] [--claims FILE] [--verbose] [CLAIM ...] — `--help` prints the rest.
# The brief's seam claims judged against a checkout; `scripts/seam_check.py` owns the flags, the root and the verdict.
set -euo pipefail
# shellcheck source=scripts/gate_refuse.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/gate_refuse.sh" || exit 2
refuse_if_piped seam_check
PY=$(checkout_python "$(dirname -- "${BASH_SOURCE[0]}")/..") ||
    gate_die "Nothing was checked; no claim was judged." "seam_check: this checkout has no .venv/bin/python — run \`uv sync\` (or ./scripts/setup.sh) first."
exec "$PY" "$(dirname -- "${BASH_SOURCE[0]}")/seam_check.py" "$@"
