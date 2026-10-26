#!/usr/bin/env bash
# THE VERIFIER BOX WRAPPER — one throwaway EC2 machine per verification; the client is quality/djb/box.
#   scripts/verifier_box.sh <subcommand> [args…]    (--help prints the synopsis; exit 0 · 1 a finding · 2 refused)
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/gate_refuse.sh" || exit 2
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(checkout_python "$ROOT")" ||
    gate_die "" "verifier_box: no ${ROOT}/.venv interpreter — ./scripts/setup.sh provisions it"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
exec "$PY" -m quality.djb.box "$@"
