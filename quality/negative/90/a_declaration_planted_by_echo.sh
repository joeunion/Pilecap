#!/usr/bin/env bash
# A drive that writes a declaration into a scratch module declares nothing itself.
plant_declaration() {
    echo "# names, never reads: docs/product/queue.md — a scratch module's declaration" >"$1"
}
