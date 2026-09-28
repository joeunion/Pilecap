# THE COLLECTION FIXTURE WORLD — what it is, and why a drive collects it
# instead of `apps/`.
#
# `scripts/tests/test_loop_scope.sh` and `scripts/tests/test_list_legs.sh` each
# ask the same class of question many times over: given a scope, a tier, a
# shard or a split, WHICH node ids does pytest end up with? Every one of those
# questions was asked of the real suite, and the real suite is four thousand
# items — so both drives declared `apps/` in their `# drives:` line and the
# selftest bank re-drove both of them on every rung that touched an app,
# whether or not the rung could have moved a single one of those answers.
#
# A SELECTION MECHANISM PROVEN OVER FIFTY ITEMS IS PROVEN. What the cases
# assert is a property of the derivation — disjointness, closure, a floor that
# refuses, a population that survives a narrowing — and none of those
# properties is a property of any particular app. So the population moves here:
# four scratch apps with their own `apps.py` and `depends_on`, one census
# module that declares itself, one module that reaches each organ kind, and
# enough members of each named always-on population to clear the floors
# `apps/conftest.py` asserts BEFORE anything is deselected. Roughly fifty
# items, all of them this directory's.
#
# THE FLOORS ARE THE TREE'S AND THE MEMBERSHIP IS THIS DIRECTORY'S, WHICH IS A
# COUPLING THIS FILE PAYS FOR. Every collection the drive runs is narrowed by
# path to this world, so `apps/conftest.py`'s named-population floors are
# asserted over THESE modules and not over the tree's. Raise a floor there and
# this world must grow a member, or the drive's own `--collect-only` refuses
# with a pytest UsageError (exit 4) and the drive reports a could-not-look it
# did not cause. Measured, not reasoned: BOXBANK-22 red on exactly that, the
# day `apps_root_modules` was re-derived 4 -> 5 and this directory still
# shipped `apps_root/test_world_root_{one..four}.py` — so a FIFTH landed here.
# The count is never typed twice: `world_install` copies the glob and the
# drive's `WORLD_TARGET` loops the same directory, so a sixth is one file.
#
# A TOKEN POPULATION GROWS WITHOUT GROWING THE WORLD. Most of the floors count
# modules whose SOURCE carries a token (`DJB_REACH_TOKENS`,
# `DJB_REACH_POPULATIONS`), so a member is one line — the token — in a module
# that is ALREADY always-on (a doors or a lifecycle module). That moves no
# selection and no item count, which keeps `WORLD_FLOOR`'s arithmetic and every
# narrowed case's answer where they were. Paid again the day the door-registry
# reach kind landed: `door_parity_census` 10 -> 14 and
# `introspect_registry_readers` 4 -> 7 were re-derived, and
# `openapi_document_readers` (18) and `mcp_catalogue_readers` (2) were new, so
# the world grew those members the same way. A PATH population
# (`apps_root_modules`, `lifecycle_registry_walkers`) still needs a file.
#
# WHAT THIS BUYS, and it is not the drives' own wall clock: it is the `apps/`
# in their `# drives:` lines. A drive that does not read `apps/` is not
# re-driven by a rung that only touched an app.
#
# WHAT IT COSTS, declared rather than discovered: the cases no longer measure
# THIS TREE's modules. An importer widening that stopped answering for
# `apps/comms` specifically, a closure that stopped walking a real
# `depends_on`, a population floor whose real members left — none of those
# reach a fixture world. The full gate's own `--loop` run and the wave bank are
# the cover, and `scripts/tests/test_shard_census.sh` is the one census that
# stayed on the real tree because its subject IS the real tree.
#
# THIS FILE IS SOURCED, NEVER EXECUTED, so it carries no shebang and no
# interpreter belt — the argument is `scripts/db.sh`'s, at scripts/db.sh:50-57.

# world_dir — the directory this library lives in.
world_dir() {
    printf '%s' "${COLLECTION_WORLD_DIR}"
}

# world_labels — the fixture apps' labels, DERIVED from the directory rather
# than typed, so an app added or removed here needs no second edit.
world_labels() {
    local one
    for one in "${COLLECTION_WORLD_DIR}"/apps/*/; do
        [ -d "$one" ] || continue
        basename "$one"
    done
}

# world_install <checkout> — put the fixture world into <checkout>/apps/.
# The apps land as ordinary apps (discovery finds their `apps.py`, so
# INSTALLED_APPS holds them for the collection) and the apps-root modules land
# beside the tree's own.
world_install() {
    local into="$1" label
    [ -d "${into}/apps" ] || return 2
    for label in $(world_labels); do
        rm -rf "${into}/apps/${label}"
        cp -R "${COLLECTION_WORLD_DIR}/apps/${label}" "${into}/apps/${label}"
    done
    cp "${COLLECTION_WORLD_DIR}"/apps_root/test_world_root_*.py "${into}/apps/"
}

# world_uninstall <checkout> — remove every byte world_install wrote. Called
# from the drives' exit traps, so a killed drive leaves no scratch app behind.
world_uninstall() {
    local into="$1" label
    [ -n "${into:-}" ] || return 0
    for label in $(world_labels); do
        rm -rf "${into}/apps/${label}"
    done
    rm -f "${into}"/apps/test_world_root_*.py
    find "${into}/apps" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
}

# world_ignore_flags <checkout> — the `--ignore=` flags that leave the fixture
# world and NOTHING ELSE collectable under `apps/`.
#
# DERIVED, never a list: every directory and every apps-root test module under
# `<checkout>/apps/` that the fixture world did not put there. A real app added
# to the tree is ignored on the day it lands, with no edit here — which is the
# whole reason this is a subtraction rather than a set of paths to collect: a
# positive path list would leave the always-on floors asserting over the real
# tree the day somebody added a fifth fixture app and forgot a line.
world_ignore_flags() {
    local into="$1" one base keep flags=""
    for one in "${into}"/apps/*/; do
        base=$(basename "$one")
        keep=0
        for label in $(world_labels); do
            [ "$base" = "$label" ] && keep=1
        done
        [ "$keep" = "1" ] && continue
        flags="${flags} --ignore=apps/${base}"
    done
    for one in "${into}"/apps/test_*.py; do
        [ -f "$one" ] || continue
        base=$(basename "$one")
        case "$base" in
        test_world_root_*) continue ;;
        esac
        flags="${flags} --ignore=apps/${base}"
    done
    printf '%s' "${flags# }"
}
