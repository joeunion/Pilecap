#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
# verify_start.sh <rung-branch> [--no-sync] [--no-loop] [<destination>] · --check [<checkout>] — `--help` prints the rest.
# The verify start; `quality/djb/rituals/verify_start.py` owns the steps, the flags and the verdict.
set -euo pipefail
# shellcheck source=scripts/gate_refuse.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/gate_refuse.sh" || exit 2
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PY=$(checkout_python "$root") ||
    gate_die "Nothing was cloned, merged or written." "verify_start: this checkout has no .venv/bin/python — run \`uv sync\` (or ./scripts/setup.sh) first."
export PYTHONPATH="${root}${PYTHONPATH:+:${PYTHONPATH}}"
exec "$PY" -m quality.djb.rituals.verify_start "$@"
