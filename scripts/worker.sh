#!/usr/bin/env bash
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

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.local}"

exec uv run python -m apps.workflows.worker
