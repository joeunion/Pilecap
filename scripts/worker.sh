#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
# The Temporal worker: a second process beside the web one.
#
#   ./scripts/worker.sh
#
# It polls the task queue this worktree owns (djb- plus the database suffix), so
# two branches' workers never steal each other's tasks. The workflows and
# activities it runs are discovered from the installed apps; nothing lists them.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f scripts/db.sh ]; then
    # shellcheck source=scripts/db.sh
    source scripts/db.sh
fi

[ -n "${DJANGO_SETTINGS_MODULE:-}" ] || [ ! -f .env ] ||
    DJANGO_SETTINGS_MODULE="$(sed -n 's/^DJANGO_SETTINGS_MODULE=//p' .env | tail -1)"
[ -n "${DJANGO_SETTINGS_MODULE:-}" ] || {
    gate_refuse "worker.sh: DJANGO_SETTINGS_MODULE is unset and .env names none — ./scripts/setup.sh writes .env with it, or export it."
    exit 2
}
export DJANGO_SETTINGS_MODULE

exec uv run python -m apps.workflows.worker
