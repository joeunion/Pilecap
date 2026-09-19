#!/usr/bin/env bash
# The `--loop` `fe` leg's tri-state. Sourced by scripts/check.sh and by
# scripts/tests/test_fe_leg.sh's 9-case harness.
# BASH ONLY, for the reason gate_ledger.sh states: sourced into an interactive
# zsh, `local path` ties to $PATH and every helper dies silently.
#
# NOT EXECUTABLE, AND THAT IS THE DECLARATION, not an oversight: this file
# reports no verdict of its own. It hands a state and an exit code to
# whoever sourced it, and the caller owns the exit status. A library beside
# secrets_scan.sh and loop_tier.sh, not an instrument beside them.
#
# ---------------------------------------------------------------------------
# WHY THREE STATES, AND WHY THEY ARE FIXTURE-PROVEN. This template ships with
# no `frontend/` at all — that is the steady state, not a defect — so on the
# real tree this leg is ALMOST ALWAYS going to report `absent`. A mechanism
# whose every live run takes the same branch is a mechanism nothing has
# proven can take the other two, so `scripts/tests/test_fe_leg.sh` drives all
# three states through synthetic fixture directories rather than depending on
# this checkout ever growing a real one. That is the whole reason this file
# is a sourced library rather than inline in check.sh: a drive has to be able
# to call `fe_leg_run` against a scratch `frontend/`-shaped directory without
# dragging the rest of the gate along.
#
# THE TREE-PRESENT/TOOLCHAIN-ABSENT CELL IS NOT INVENTED HERE. It is the same
# decision `quality/worlds.py`'s `tree_verdict` makes for a `needs_tree:`
# rules.yaml rule: tree absent -> skip printed (a rule about a tree nobody has
# must not cost that product a red gate forever); tree present, toolchain
# absent -> could-not-look, which outranks a pass; both present -> run. This
# leg is check.sh's OWN gate leg rather than a rules.yaml rule, so it cannot
# import that function without inventing a scope-kind rule this leg is not —
# but it is written to answer the identical three questions in the identical
# order, and this comment is what makes "did the two drift apart" a checkable
# claim rather than an assumption. `untouched` is this leg's OWN fourth cell,
# layered on top: a rung's own-app tiering, one door over from the pytest
# leg's, for the reason stated at each function below.
#
# GATE-VS-UNTRACKED-FRONTEND, MEASURED (criterion 4). A product grows its
# `frontend/` before it commits it, so the banked question was what an
# UNTRACKED one does to the gate legs that were already here. It is THREE
# populations, and they do not answer the same way. An earlier blanket
# "measured, no perturbation anywhere" reading was WRONG on the third; it is
# corrected here rather than restated.
#
#   1 · the secret walk (`secrets_scan_changed_files`, secrets_scan.sh) —
#       UNPERTURBED. It derives its file set from `git diff` / `git ls-files`,
#       and neither reports an untracked path, so the walk sees the identical
#       set with and without one. MEASURED against a planted `frontend/`
#       (package.json + a src file): 9 changed files before, 9 after, 0 of
#       them under `frontend/`, derive rc 0.
#   2 · the archaeology census (`archaeology_loop`, archaeology_lib.sh) —
#       UNPERTURBED, and for the same reason at one remove: it narrows the
#       SAME derived set down to bucket SHIP. MEASURED against the same
#       plant: 9 changed bucket-SHIP files scanned, 0 under `frontend/`,
#       leg rc 0.
#   3 · the gate-ledger MEASURED TREE HASH (`gate_measured_tree`,
#       gate_ledger.sh:112-128) — PERTURBED, AND CORRECTLY SO. That function
#       does not read `git diff` at all: it builds a scratch index and runs
#       `git add -A` into it (gate_ledger.sh:120), which stages untracked
#       content — everything `.gitignore` does not exclude, and `.gitignore`
#       excludes `node_modules/` but NOT `frontend/` itself. MEASURED: the
#       stage-2 verifier observed 170cd5b... -> d68d167...; reproduced on a
#       second checkout as 206d6ee... -> 1bf308f9... The absolute hashes are
#       per-checkout and are not the claim; the MOVE is.
#
# WHY 3 IS NOT A DEFECT, and why no walk exclusion is added: the ledger's key
# answers "what content did the gate actually measure", and an uncommitted
# `frontend/` IS content the gate can read. A banked green verdict SHOULD stop
# applying the moment such a tree appears — exactly as it already does for any
# other uncommitted change. Narrowing `git add -A` to hold the hash still
# would make a banked verdict vouch for a tree nobody measured, which is the
# one failure the ledger exists to prevent. So the perturbation is the
# declared, intended answer, not a residue to clean up.
# ---------------------------------------------------------------------------

# Overridable so a drive never has to be the real checkout's frontend/ — the
# whole reason the tri-state is fixture-proven rather than tree-observed.
FE_FRONTEND_DIR="${FE_FRONTEND_DIR:-frontend}"

# fe_leg_touched_frontend <changed-file-list (NUL-separated)>
#
# True (0) when the list names at least one path under $FE_FRONTEND_DIR/.
fe_leg_touched_frontend() {
    local list=$1 f
    while IFS= read -r -d '' f; do
        case "$f" in
        "$FE_FRONTEND_DIR"/*) return 0 ;;
        esac
    done <"$list"
    return 1
}

# ---------------------------------------------------------------------------
# THE CONTRACT SURFACE — the visibility half of this leg, and it is a DISCLOSURE rather
# than a finding.
#
# THE DEFECT, measured on this file before this block existed. `fe_leg_run`'s
# `untouched` fast path keys on `$FE_FRONTEND_DIR/*` and nothing else, so a
# change to a BACKEND file that stales the committed client printed:
#
#   $ changed set = apps/example/api.py, config/api.py
#     UNTOUCHED (fast path) — frontend/ is on this tree but the active
#     rung changed nothing under it; nothing frontend-shaped is re-run.
#     fe_leg_run rc=0  FE_LEG_STATE=untouched
#
# That is exactly the sibling product's measured class: a change outside `frontend/` that
# stales the frontend is invisible to every gate a builder can run, and the
# blow-up lands on the shared train. It COMPOUNDS with the byte-pin
# (`frontend/scripts/pin_client.sh`), which is the one instrument that would
# catch it and is wired into no gate leg at all.
#
# THE SPLIT: DISCLOSURE AT RUNG TIME, REGENERATION AT BANK TIME. This leg does
# NOT regenerate and does not compare bytes — a regeneration needs `npx`, Node
# and a schema export, which is a minute the per-rung loop does not have and a
# could-not-look on any machine without Node. It NAMES the suspicion, so the
# builder is told; `scripts/pm_fold.sh` regenerates at the bank and either
# commits the shift or refuses, which is where the byte-pin's tooth actually
# closes. A named suspicion the builder can act on beats a silent UNTOUCHED
# they cannot.
#
# THE PREDICATE IS DERIVED FROM WHAT THE GENERATOR READS, not from a guess about
# what "backend" means. `scripts/gen_client.sh` exports the document with
# `manage.py export_openapi_schema --api config.api.api` and hands it to
# `openapi-typescript`. So what can move the document is:
#
#   config/api.py           the NinjaAPI object the exporter is pointed at, named
#                           verbatim on gen_client.sh's own command line
#   config/urls.py          owns the version segment, so it owns every path in
#                           the document (CLAUDE.md, "the doors")
#   apps/*/api.py           the discovered routers: every path, operation, tag
#                           and @refuses set
#   apps/*/schemas.py       every entry under components.schemas
#   apps/core/exceptions.py the refusal registry the document's `x-refusal-codes`
#                           is derived from (rule 47, ADR core-23) — verified
#                           present in frontend/openapi.json at rung time
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * A DOCUMENT MOVED BY ANYTHING ELSE. A settings change, a dependency bump
#     that changes django-ninja's serialisation, a model field a schema resolves
#     from — none is on this list. This is a suspicion list, not a proof, and it
#     is deliberately the five things gen_client.sh's own command line reaches.
#     The byte-pin at the bank is what actually decides.
#   * WHETHER THE CLIENT IS ACTUALLY STALE. It is not compared here. A change to
#     a docstring in an `api.py` names the client as a suspect and the fold then
#     finds nothing to do. A false suspicion costs a printed line.
#   * `apps/*/` MATCHING DEEPER. `case` globbing lets `*` cross `/`, so
#     `apps/a/b/api.py` matches too. Wider than the convention, never narrower,
#     and this tree has no such path.
FE_CONTRACT_SURFACE='config/api.py
config/urls.py
apps/*/api.py
apps/*/schemas.py
apps/core/exceptions.py'

# fe_leg_contract_surface_changes <changed-file-list (NUL-separated)>
#
# Prints every path in the list that is on the contract surface, one per line.
# Silent when there are none.
fe_leg_contract_surface_changes() {
    local list=$1 f pat
    while IFS= read -r -d '' f; do
        while IFS= read -r pat; do
            [ -n "$pat" ] || continue
            # shellcheck disable=SC2254  # the pattern is the point: $pat is a glob
            case "$f" in
            $pat)
                printf '%s\n' "$f"
                break
                ;;
            esac
        done <<EOF
$FE_CONTRACT_SURFACE
EOF
    done <"$list"
}

# fe_leg_toolchain_present — overridable (FE_PNPM) so a drive can name a shim
# without touching this checkout's real PATH.
fe_leg_toolchain_present() {
    command -v "${FE_PNPM:-pnpm}" >/dev/null 2>&1
}

# fe_leg_frozen_lockfile <frontend-dir>
#
# THE TARGET CLASS (criterion 3): a textually-clean lockfile that no longer
# satisfies package.json — a dependency bumped in one and not regenerated in
# the other. `pnpm install --frozen-lockfile` is the conventional CI form of
# this check everywhere pnpm ships: it refuses (nonzero) the moment the
# lockfile does not resolve every manifest entry exactly, without pnpm ever
# rewriting it. Exit: 0 clean · 1 the lockfile no longer satisfies the
# manifest · 2 could-not-look (no manifest, no lockfile to freeze).
fe_leg_frozen_lockfile() {
    local dir=$1
    [ -f "$dir/package.json" ] || {
        echo "!! fe leg: $dir/package.json is missing — the frozen-lockfile check has no" >&2
        echo "   manifest to read. Could-not-look, not a violation." >&2
        return 2
    }
    [ -f "$dir/pnpm-lock.yaml" ] || {
        echo "!! fe leg: $dir/pnpm-lock.yaml is missing — a frontend/ tree ships an" >&2
        echo "   unfrozen dependency set. Could-not-look, not a violation." >&2
        return 2
    }
    (cd "$dir" && "${FE_PNPM:-pnpm}" install --frozen-lockfile --reporter=silent)
}

# fe_leg_tests <frontend-dir>
#
# Runs the declared "test" script when package.json has one; prints and
# returns 0 when it does not, because a frontend/ tree that has not grown a
# test script yet is the scaffold's own frontier, not this leg's finding.
fe_leg_tests() {
    local dir=$1
    if ! python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    sys.exit(1)
sys.exit(0 if "test" in d.get("scripts", {}) else 1)
' "$dir/package.json" >/dev/null 2>&1; then
        echo "  no \"test\" script declared in $dir/package.json — nothing run"
        return 0
    fi
    (cd "$dir" && "${FE_PNPM:-pnpm}" run test)
}

# fe_leg_run <changed-file-list (NUL-separated, secrets_scan_changed_files'
# own output shape)>
#
# The whole state machine, one function, so a drive and check.sh call the exact
# same decision. Sets FE_LEG_STATE (absent|untouched|suspect|full — cleared to
# "" when the toolchain is absent, which is could-not-look rather than a state).
# `suspect` splits the old `untouched`: same fast path,
# same exit 0, nothing re-run — but the backend contract surface moved, so the
# committed client is NAMED as in question instead of being reassured about.
# Exit: 0 clean (absent, untouched, suspect, or a clean full run) · 1 a finding
# in the full state (a frozen lockfile mismatch or a failing test script) · 2
# could-not-look (frontend/ present, touched, and its toolchain is not).
fe_leg_run() {
    local changed_list=$1 lockrc
    FE_LEG_STATE=""

    if [ ! -d "$FE_FRONTEND_DIR" ]; then
        FE_LEG_STATE=absent
        echo "  ABSENT — $FE_FRONTEND_DIR/ is not on this tree, the template's steady"
        echo "  state; every JS static rule and frontend test derives to nothing here."
        return 0
    fi

    if ! fe_leg_touched_frontend "$changed_list"; then
        # `untouched` used to be the ONLY answer here, and it was wrong
        # for the population above — a backend contract change that stales the
        # committed client printed the fast path's own reassurance. The suspect
        # state is a disclosure and exits 0: nothing is re-run, nothing is
        # regenerated, and the builder is told which files put the client in
        # question.
        local suspects
        suspects="$(fe_leg_contract_surface_changes "$changed_list")"
        if [ -n "$suspects" ]; then
            FE_LEG_STATE=suspect
            echo "  CLIENT SUSPECT — $FE_FRONTEND_DIR/ is on this tree and the active rung"
            echo "  changed nothing under it, but it DID change the contract surface the"
            echo "  committed client is generated from:"
            printf '%s\n' "$suspects" | while IFS= read -r f; do
                [ -n "$f" ] || continue
                echo "    $f"
            done
            echo "  The committed client and document may now disagree with this checkout, and"
            echo "  a stale generated client still COMPILES. Nothing is re-run here and this is"
            echo "  not a finding."
            # ONE COMMAND, AT THE SITE OF THE DISCLOSURE, IN PLACE OF FOUR LINES
            # OF ADVICE. The advice named three different things a builder could
            # do and left them to pick; every builder who met this state then
            # went looking for which. The offer is the same command whether this
            # leg discloses (here) or a consumer's leg refuses, so the sentence
            # travels — `docs/product/build-contract.md` says so.
            echo "  offer: ./scripts/rung_tidy.sh --client"
            echo "    It regenerates both files through ./frontend/scripts/pin_client.sh"
            echo "    --write, into the working tree, staging nothing — so the shift lands in"
            echo "    the caller's own diff instead of in the bank's fold commit."
            return 0
        fi
        FE_LEG_STATE=untouched
        echo "  UNTOUCHED (fast path) — $FE_FRONTEND_DIR/ is on this tree but the active"
        echo "  rung changed nothing under it; nothing frontend-shaped is re-run."
        return 0
    fi

    if ! fe_leg_toolchain_present; then
        echo "!! COULD NOT LOOK — $FE_FRONTEND_DIR/ IS on this tree and the active rung" >&2
        echo "   touched it, and its toolchain (${FE_PNPM:-pnpm}) is not on PATH. A tree" >&2
        echo "   with a subject and no instrument is could-not-look, never a clean scan." >&2
        return 2
    fi

    FE_LEG_STATE=full
    echo "  FULL — $FE_FRONTEND_DIR/ touched by the active rung, toolchain present."
    echo "  -- frozen-lockfile --"
    fe_leg_frozen_lockfile "$FE_FRONTEND_DIR"
    lockrc=$?
    if [ "$lockrc" = "2" ]; then
        return 2
    elif [ "$lockrc" != "0" ]; then
        echo "!! fe leg: the lockfile no longer satisfies package.json" >&2
        echo "   (pnpm install --frozen-lockfile exited $lockrc)." >&2
        return 1
    fi
    echo "  ok — pnpm-lock.yaml satisfies package.json"

    echo "  -- frontend tests --"
    fe_leg_tests "$FE_FRONTEND_DIR" || return 1
    return 0
}
