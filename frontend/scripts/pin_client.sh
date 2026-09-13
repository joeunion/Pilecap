#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made. The argument, measured
# on this tree, is `scripts/rung_start.sh`'s header.
[ -n "${BASH_VERSION:-}" ] || {
    echo "${0##*/}: must run under bash — not sh, not zsh. Try \`bash ${0}\`." >&2
    exit 2
}
case ":${SHELLOPTS:-}:" in
*:posix:*)
    echo "${0##*/}: bash is in POSIX mode — which is what \`sh ${0}\` does on a" >&2
    echo "  machine whose /bin/sh is bash. Try \`bash ${0}\`." >&2
    exit 2
    ;;
esac
# THE BYTE-PIN. The committed client is byte-identical to what this checkout
# would generate right now, or this exits 1 and prints the diff.
#
#   ./frontend/scripts/pin_client.sh            # assert. 0 identical · 1 drift · 2 could not look
#   ./frontend/scripts/pin_client.sh --write    # regenerate and commit the answer
#
# WHY A PIN AT ALL. `fe-conventions` §4 Law 3 says the generated client's types
# are the contract and are used verbatim, never re-declared. That sentence stops
# being true the moment the committed client and the document disagree — and the
# disagreement is silent, because a stale client still COMPILES. The pin makes
# drift loud: change a schema in `apps/`, forget to regenerate, and this says so
# with the exact bytes.
#
# THE SCRIPT LIVES HERE; THE TOOTH LIVES IN THE GATE. This file is the frontend
# rung's own instrument and is run by hand or by `pnpm pin:client`. Wiring it
# into `scripts/check.sh` is a separate rung's territory (P16 W2 · R-c) and this
# script deliberately does not reach into `scripts/` to do it — neither rung
# edits the other's files.
#
# GENERATION IS NOT REIMPLEMENTED HERE. It is `scripts/gen_client.sh`, the
# repository's one generator: offline by construction (the document is exported
# from the checkout, never fetched from a running server), and pinned to one
# `openapi-typescript` version so two runs cannot differ. This script only
# points it at a scratch directory and compares.
#
# EXIT: 0 the committed client is current · 1 it has drifted (or was written,
# under --write, and the tree now differs) · 2 could not look — no generator, no
# node, an export that failed. 2 outranks a pass, here as everywhere.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
FRONTEND="$(dirname "$HERE")"
ROOT="$(dirname "$FRONTEND")"

GEN="$ROOT/scripts/gen_client.sh"
COMMITTED_CLIENT="$FRONTEND/src/api/generated/schema.d.ts"
COMMITTED_DOC="$FRONTEND/openapi.json"

WRITE=0
case "${1:-}" in
"") ;;
--write) WRITE=1 ;;
*)
    echo "${0##*/}: unknown argument '$1'. Usage: ${0##*/} [--write]" >&2
    exit 2
    ;;
esac

[ -x "$GEN" ] || {
    echo "!! $GEN is not executable — the generator is this script's whole engine (exit 2)" >&2
    exit 2
}

SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

# `gen_client.sh` writes a `.gitignore` holding `*` into whatever directory it
# is pointed at — a generated client is a build artefact of the tree it came
# from, and that rule travels with the directory. Which is exactly why it is
# pointed at a SCRATCH directory here and the bytes are copied in afterwards:
# generating straight into `src/api/generated/` would plant a `.gitignore` that
# hides the very file this pin exists to keep committed.
if ! SCHEMA="$SCRATCH/openapi.json" "$GEN" "$SCRATCH/schema.d.ts" >"$SCRATCH/gen.log" 2>&1; then
    status=$?
    echo "!! the generator could not produce a client (exit $status). Its output:" >&2
    sed 's/^/   /' "$SCRATCH/gen.log" >&2
    # The generator's own codes carry through: 2 is "I could not look" (no npx,
    # no node), 1 is "I looked and this checkout cannot export a schema".
    exit "$status"
fi

if [ "$WRITE" -eq 1 ]; then
    mkdir -p "$(dirname "$COMMITTED_CLIENT")"
    cp "$SCRATCH/schema.d.ts" "$COMMITTED_CLIENT"
    cp "$SCRATCH/openapi.json" "$COMMITTED_DOC"
    echo "wrote $COMMITTED_CLIENT"
    echo "wrote $COMMITTED_DOC"
    echo "Commit both. They are one artefact of one commit of this checkout."
    exit 0
fi

drift=0
for pair in "$COMMITTED_DOC:$SCRATCH/openapi.json" "$COMMITTED_CLIENT:$SCRATCH/schema.d.ts"; do
    committed="${pair%%:*}"
    fresh="${pair##*:}"
    if [ ! -f "$committed" ]; then
        echo "!! $committed is missing — nothing is pinned (exit 1)" >&2
        drift=1
        continue
    fi
    if ! diff -u "$committed" "$fresh" >"$SCRATCH/diff.txt" 2>&1; then
        echo "!! $committed has drifted from what this checkout generates:" >&2
        sed 's/^/   /' "$SCRATCH/diff.txt" >&2
        drift=1
    fi
done

if [ "$drift" -ne 0 ]; then
    echo "" >&2
    echo "   Regenerate with: ./frontend/scripts/pin_client.sh --write" >&2
    echo "   Client regeneration is a DELIBERATE, SERIAL rung (fe-conventions §9)." >&2
    exit 1
fi

echo "the committed client and document are byte-identical to a fresh generation"
