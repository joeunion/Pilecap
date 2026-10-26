#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
# proof_from_zero.sh [--dry-run] [--ref <rev>] [--dest <dir>] [--out <dir>] — `--help` prints the rest.
# The proof from zero; `quality/djb/rituals/proof_from_zero.py` owns the steps, the flags and the record.
set -euo pipefail
# shellcheck source=scripts/gate_refuse.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/gate_refuse.sh" || exit 2
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PY=$(checkout_python "$root") ||
    gate_die "Nothing was cloned or written." "proof_from_zero: this checkout has no .venv/bin/python — run \`uv sync\` (or ./scripts/setup.sh) first."
export PYTHONPATH="${root}${PYTHONPATH:+:${PYTHONPATH}}"
exec "$PY" -m quality.djb.rituals.proof_from_zero "$@"
