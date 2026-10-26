#!/usr/bin/env bash
# The provisioning steps setup.sh and rung_start.sh both run, sourced; each caller owns its order.
#   frontend_install <root>   `pnpm install --frozen-lockfile` in <root>/frontend, or a printed skip; never fatal
# FRONTEND_NOTE carries a failed install to the caller's footer; FE_PNPM is `scripts/fe_gate.sh`'s name for the tool.
FRONTEND_NOTE=""

frontend_install() {
    local root="$1" dir pnpm rc=0
    dir="$root/frontend"
    pnpm="${FE_PNPM:-pnpm}"

    if [ ! -d "$dir" ]; then
        printf '   frontend     skipped — no frontend/ on this tree\n'
        return 0
    fi
    if ! command -v "$pnpm" >/dev/null 2>&1; then
        printf '   frontend     skipped — pnpm not on PATH; the fe leg will be could-not-look\n'
        printf '                if the work touches frontend/\n'
        return 0
    fi

    # gen_client.sh uses npx and reads nothing here; the line below says so on every run.
    printf '   frontend/node_modules: for the fe leg'"'"'s FULL state and pnpm pin:client; gen_client.sh uses npx and is unaffected\n'
    set +e
    (cd "$dir" && "$pnpm" install --frozen-lockfile)
    rc=$?
    set -e
    if [ $rc -eq 0 ]; then
        printf '   frontend     pnpm install --frozen-lockfile (%s)\n' "$dir"
        return 0
    fi

    # Loud and not fatal: the footer carries FRONTEND_NOTE.
    FRONTEND_NOTE="frontend/node_modules was not installed (pnpm exited ${rc})"
    printf '\n   !! no frontend/node_modules: pnpm install --frozen-lockfile exited %s.\n' "$rc" >&2
    printf '      The fe leg'"'"'s FULL state will pay the cold install, and `pnpm\n' >&2
    printf '      pin:client` will not run until it is fixed. A lockfile that no\n' >&2
    printf '      longer satisfies package.json is the usual cause, and that is a\n' >&2
    printf '      finding for the fe leg to report rather than for this script to.\n' >&2
    printf '      THIS IS NOT FATAL: a rung that touches nothing under frontend/\n' >&2
    printf '      needs nothing here, and the footer says so rather than this\n' >&2
    printf '      script deciding for you.\n\n' >&2
    return 0
}

