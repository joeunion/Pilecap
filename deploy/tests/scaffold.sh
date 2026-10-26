# deploy/tests/scaffold.sh — the files a deploy executable reaches beside itself,
# copied into a drive's scratch deployment. A LIBRARY, sourced by the deploy
# drives after the preamble; never executed, mode 644.
#
# A deploy script derives everything from its own directory, so a drive that
# runs a COPY of one in a scratch tree has to give that tree what the script
# sources: the belt (`scripts/bash_only.sh`), the scaffold (`deploy/lib.sh`) and
# the seam it speaks through (`scripts/gate_refuse.sh`), the env file's one
# reader and writer (`deploy/envfile.py`), and the checkout digest
# (`scripts/db.sh`). Named once, here, so a file added to that set is added to
# every drive's world in one line.
#
# WHAT IT DOES NOT COVER
# does-not-cover: a file a deploy script starts sourcing that is not listed here — the drive running that script fails at its first line, loudly, and the line goes here.

DEPLOY_SCAFFOLD_FILES="scripts/bash_only.sh scripts/gate_refuse.sh scripts/ci_stack.sh scripts/db.sh deploy/lib.sh deploy/envfile.py"

# deploy_scaffold_into <root> — copy the scaffold set from this checkout into
# the scratch tree at <root>, at the same relative paths.
deploy_scaffold_into() {
    local root="${1:-}" f
    drive_require_scratch DEPLOY_SCAFFOLD_ROOT "$root"
    for f in $DEPLOY_SCAFFOLD_FILES; do
        mkdir -p "$root/$(dirname "$f")" &&
            cp "$f" "$root/$f" ||
            drive_cannot_look "could not copy $f into the scratch tree at $root"
    done
}
