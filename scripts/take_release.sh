#!/usr/bin/env bash
# THE release road: `python -m quality.djb.rituals.take_release` on this checkout's interpreter — fetch, census, merge, fold, sdk, gate — every step and verdict is the module's.
# Invariant: the checkout's database is exported first (`scripts/db.sh`); `-P` and PYTHONPATH make the import this checkout's package.
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
. "$root/scripts/gate_refuse.sh" || exit 2
py=$(checkout_python "$root") || {
    echo "!! scripts/take_release.sh: COULD NOT LOOK — ${root}/.venv/bin/python is absent; run ./scripts/setup.sh" >&2
    exit 2
}
. "$root/scripts/db.sh" >/dev/null || exit 2
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
exec "$py" -P -m quality.djb.rituals.take_release "$@"
