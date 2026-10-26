#!/usr/bin/env bash
# THE gate: `python -m quality.djb gate` on this checkout's interpreter — every mode, refusal and verdict is the package's.
# Invariant: no venv is could-not-look (exit 2), except `--list-legs`, which is the stdlib floor on any python3.
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
. "$root/scripts/gate_refuse.sh" || exit 2
py=$(checkout_python "$root") || case "${1:-}" in
--list-legs) py=python3 ;;
*) echo "!! scripts/check.sh: COULD NOT LOOK — ${root}/.venv/bin/python is absent; run ./scripts/setup.sh" >&2 && exit 2 ;;
esac
cd "$root"
exec "$py" -m quality.djb gate "$@"
