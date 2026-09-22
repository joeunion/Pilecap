#!/usr/bin/env bash
# CLASS (b), FORM 1 — A DRAWER NOBODY WROTE DOWN.
#
# A template-owned script that runs a list of things out of a `local/` drawer
# beside it. The drawer is real, the discovery works, and no row of
# `docs/product/build-contract.md`'s fenced `drawers` block names it — so a
# product reading that table would never find the seam, and would edit this
# file instead. That is the whole failure ADR platform-extension-1 exists to
# close, arriving one rung at a time as each new drawer is built.
set -euo pipefail
for step in scripts/local/stage.d/*.sh; do
    [ -x "$step" ] || continue
    "$step"
done
