#!/usr/bin/env bash
# THE divergence census: `python -m quality.djb.rituals.divergence` on this checkout's interpreter — every refusal and verdict is the module's.
# Invariant: the caller's cwd is kept (the module reads it); `-P` and PYTHONPATH make the import this checkout's package.
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
. "$root/scripts/gate_refuse.sh" || exit 2
py=$(checkout_python "$root") || {
    echo "!! scripts/divergence_census.sh: COULD NOT LOOK — ${root}/.venv/bin/python is absent; run ./scripts/setup.sh" >&2
    exit 2
}
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
exec "$py" -P -m quality.djb.rituals.divergence "$@"
