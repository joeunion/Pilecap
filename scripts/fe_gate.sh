#!/usr/bin/env bash
# The `fe` leg's four states (absent, untouched, suspect, full). Sourced by scripts/check.sh and by
# quality/tests/test_fe_leg.py's harness.
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
# proven can take the other two, so `quality/tests/test_fe_leg.py` drives all
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
# (`frontend/scripts/pin_client.sh`), the one instrument that catches it —
# which this leg now runs (`fe_leg_pin`).
#
# THE SPLIT: the suspect state runs the byte pin when the toolchain and the pin
# exist (drift is 1 with the `--client` offer, could-not-look 2); otherwise it
# discloses and `scripts/pm_fold.sh` regenerates at the bank.#
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
#     `apps/<a>/<b>/api.py` matches too. Wider than the convention, never narrower,
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
# manifest — a code of pnpm's lockfile-drift family (OUTDATED_LOCKFILE,
# NO_LOCKFILE, LOCKFILE_*, FROZEN_LOCKFILE_WITH_OUTDATED_LOCKFILE,
# BROKEN_LOCKFILE), each answered by regenerating the lockfile · 2
# could-not-look (no manifest, no lockfile to freeze, or pnpm failed for a
# reason of its own — a fetch, a crash with no code), with pnpm's first
# error line.
fe_leg_frozen_lockfile() {
    local dir=$1 said log rc=0
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
    log=$(mktemp "${TMPDIR:-/tmp}/fe-frozen-lockfile.XXXXXX") || {
        echo "!! fe leg: no scratch file for pnpm's answer — could-not-look." >&2
        return 2
    }
    (cd "$dir" && "${FE_PNPM:-pnpm}" install --frozen-lockfile) >"$log" 2>&1 || rc=$?
    if [ "$rc" = "0" ]; then
        rm -f "$log"
        return 0
    fi
    said=$(grep -m1 'ERR_' "$log" || grep -m1 -v '^[[:space:]]*$' "$log" || true)
    said=${said#"${said%%[![:space:]]*}"}
    [ -n "$said" ] || said="(nothing)"
    if grep -qE 'ERR_PNPM_(OUTDATED_LOCKFILE|NO_LOCKFILE|LOCKFILE_[A-Z_]+|FROZEN_LOCKFILE_WITH_OUTDATED_LOCKFILE|BROKEN_LOCKFILE)' "$log"; then
        echo "!! fe leg: the lockfile no longer satisfies package.json" >&2
        echo "   (pnpm install --frozen-lockfile exited $rc)." >&2
        echo "   pnpm said: ${said:0:400}" >&2
        rm -f "$log"
        return 1
    fi
    echo "!! fe leg: pnpm install --frozen-lockfile exited $rc and named no lockfile drift —" >&2
    echo "   could-not-look, not a violation; regenerating the lockfile will not fix it." >&2
    echo "   pnpm said: ${said:0:400}" >&2
    rm -f "$log"
    return 2
}

# fe_leg_script <frontend-dir> <script> — run a script package.json declares,
# or print that it is not declared and return 0. Any non-zero is a finding (1):
# `tsc --noEmit` exits 2 on a type error, so a script's 2 is not this seam's 2.
fe_leg_script() {
    local dir=$1 script=$2 rc=0
    if ! python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    sys.exit(1)
sys.exit(0 if sys.argv[2] in d.get("scripts", {}) else 1)
' "$dir/package.json" "$script" >/dev/null 2>&1; then
        echo "  no \"$script\" script declared in $dir/package.json — nothing run"
        return 0
    fi
    (cd "$dir" && "${FE_PNPM:-pnpm}" run "$script") || rc=$?
    [ "$rc" = "0" ] || return 1
}

# fe_leg_tests <frontend-dir> — the declared "test" script (kept by name: three
# drives call it).
fe_leg_tests() {
    fe_leg_script "$1" test
}

# fe_leg_pin <frontend-dir> — the byte pin (`<dir>/scripts/pin_client.sh`),
# its 0/1/2 passed through; absent, nothing runs and the line says so.
fe_leg_pin() {
    local dir=$1 rc=0
    if [ ! -x "$dir/scripts/pin_client.sh" ]; then
        echo "  no executable $dir/scripts/pin_client.sh — the byte pin is not run"
        return 0
    fi
    "$dir/scripts/pin_client.sh" || rc=$?
    case "$rc" in
    0) return 0 ;;
    2) return 2 ;;
    *) return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# THE MODE, AND WHY THE FAST-PAIR ECONOMY STOPS AT THE FULL GATE (ratified
# by the PM, 2026-09-21).
#
# `untouched` and `suspect` are a RUNG-TIME economy: the per-rung loop is a
# builder's inner loop, and re-running two pnpm commands over a frontend the
# active rung never touched buys that builder nothing. The full gate is not
# that. A bank writes a verdict row naming `fe` as a leg that RAN, and the
# pre-push wall reads that row as "a full gate has passed these bytes" — so a
# bank that took the fast path vouched for a frontend nobody installed and
# nobody tested. MEASURED on this tree at f800ab5b: `check.sh --leg static` —
# one shard of a bank — printed `UNTOUCHED (fast path)` and `(fe: 0s)` while
# the unit's own summary named `fe` among the legs it had run.
#
# SO THE MODE DECIDES, AND THE CALLER HANDS IT OVER VERBATIM. `check.sh` passes
# its own `$MODE`:
#
#   ""       the FULL gate (and `--bank`/`--pr`, which normalise to it) -> WHOLE
#   --leg    one unit of the full gate, i.e. a bank shard               -> WHOLE
#   --loop   the per-rung gate                                          -> change-aware
#   --fast   the pre-commit legs                                        -> change-aware
#
# WHOLE means the touched-frontend question is never asked: `absent` still
# short-circuits (a tree with no `frontend/` has nothing to install), and
# everything else is `full` — toolchain absent is then exit 2, could-not-look,
# exactly as it already is for a touched frontend, because a bank that could
# not look at the frontend must not bank a row that says it did.
#
# AN OMITTED MODE IS CHANGE-AWARE, AND THAT IS A CONTRACT, not a default that
# drifted: three drives call this function with one argument to drive the
# tri-state itself (`quality/tests/test_fe_leg.py`'s nine cases,
# `quality/tests/test_tidy.py`'s client offer, `quality/tests/test_fold.py`'s
# suspect/plain pair), and every one of them is about the per-rung states. An
# ABSENT second argument and an EMPTY one therefore mean different things here
# — `""` is the full gate's own `$MODE` and must run the leg whole — so this
# reads `$#` rather than `${2:-}`.
#
# THE COST IS PRINTED, NOT ESTIMATED. The ratification names two pnpm commands
# per bank as the price; a price nobody measures is a price that grows in
# silence, so the `full` state times each command and prints the pair and the
# total on its own line.
# ---------------------------------------------------------------------------

# fe_leg_run <changed-file-list (NUL-separated, secrets_scan_changed_files'
# own output shape)> [<mode: check.sh's $MODE, verbatim>]
#
# The whole state machine, one function, so a drive and check.sh call the exact
# same decision. Sets FE_LEG_STATE (absent|untouched|suspect|full — cleared to
# "" when the toolchain is absent, which is could-not-look rather than a state).
# `suspect` splits the old `untouched`: same fast path,
# same exit 0, nothing re-run — but the backend contract surface moved, so the
# committed client is NAMED as in question instead of being reassured about.
# Under the WHOLE modes (see above) neither of those two states is reachable.
# Exit: 0 clean (absent, untouched, suspect, or a clean full run) · 1 a finding
# in the full state (a frozen lockfile mismatch or a failing test script) · 2
# could-not-look (frontend/ present, the toolchain is not, and this mode was
# going to look at it).
fe_leg_run() {
    local changed_list=$1 lockrc mode whole="" t0 lock_secs
    if [ "$#" -ge 2 ]; then mode=$2; else mode="--loop"; fi
    case "$mode" in
    "" | --leg) whole=1 ;;
    esac
    FE_LEG_STATE=""

    if [ ! -d "$FE_FRONTEND_DIR" ]; then
        FE_LEG_STATE=absent
        echo "  ABSENT — $FE_FRONTEND_DIR/ is not on this tree, the template's steady"
        echo "  state; every JS static rule and frontend test derives to nothing here."
        return 0
    fi

    if [ -n "$whole" ]; then
        echo "  WHOLE RUN — this is the ${mode:-full} gate, which banks a verdict row naming"
        echo "  \`fe\` as a leg that ran, so the frontend's frozen-lockfile install and its"
        echo "  declared tests run whatever the active rung touched. The untouched/suspect"
        echo "  fast path belongs to --loop and --fast (scripts/fe_gate.sh, THE MODE)."
    elif ! fe_leg_touched_frontend "$changed_list"; then
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
            echo "  a stale generated client still COMPILES."
            # The pin decides the suspicion when it can run; otherwise it stays
            # a disclosure and the fold's regeneration is the tooth.
            if fe_leg_toolchain_present && [ -x "$FE_FRONTEND_DIR/scripts/pin_client.sh" ]; then
                local pin_rc=0
                echo "  -- pin --"
                fe_leg_pin "$FE_FRONTEND_DIR" || pin_rc=$?
                if [ "$pin_rc" = "0" ]; then
                    echo "  the byte pin holds — the suspicion is cleared."
                    return 0
                fi
                if [ "$pin_rc" = "2" ]; then
                    echo "!! fe leg: the byte pin COULD NOT LOOK — see above." >&2
                    return 2
                fi
                echo "RED: fe leg: the committed client has drifted from this checkout's contract." >&2
                echo "  offer: ./scripts/rung_tidy.sh --client"
                echo "    It regenerates both files through ./frontend/scripts/pin_client.sh"
                echo "    --write, into the working tree, staging nothing."
                return 1
            fi
            echo "  The byte pin was not run (no toolchain on PATH, or no executable"
            echo "  $FE_FRONTEND_DIR/scripts/pin_client.sh); this is a disclosure, not a finding."
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
        echo "!! COULD NOT LOOK — $FE_FRONTEND_DIR/ IS on this tree and this run was going" >&2
        echo "   to look at it, and its toolchain (${FE_PNPM:-pnpm}) is not on PATH. A tree" >&2
        echo "   with a subject and no instrument is could-not-look, never a clean scan." >&2
        return 2
    fi

    FE_LEG_STATE=full
    if [ -n "$whole" ]; then
        echo "  FULL — $FE_FRONTEND_DIR/ on this tree, toolchain present, run whole for this mode."
    else
        echo "  FULL — $FE_FRONTEND_DIR/ touched by the active rung, toolchain present."
    fi
    echo "  -- frozen-lockfile --"
    t0=$(date +%s)
    fe_leg_frozen_lockfile "$FE_FRONTEND_DIR"
    lockrc=$?
    lock_secs=$(($(date +%s) - t0))
    if [ "$lockrc" = "2" ]; then
        return 2
    elif [ "$lockrc" != "0" ]; then
        return 1
    fi
    echo "  ok — pnpm-lock.yaml satisfies package.json"

    # Every sub-step runs and is timed; 2 outranks 1 in the composed status.
    local step step_rc worst=0 costs="frozen-lockfile ${lock_secs}s" total=$lock_secs secs failed=""
    for step in typecheck lint test pin; do
        echo "  -- ${step} --"
        t0=$(date +%s)
        step_rc=0
        if [ "$step" = "pin" ]; then
            fe_leg_pin "$FE_FRONTEND_DIR" || step_rc=$?
        else
            fe_leg_script "$FE_FRONTEND_DIR" "$step" || step_rc=$?
        fi
        secs=$(($(date +%s) - t0))
        costs="${costs} + ${step} ${secs}s"
        total=$((total + secs))
        if [ "$step_rc" = "2" ]; then
            echo "!! fe leg: the ${step} step COULD NOT LOOK — see above." >&2
            worst=2
            failed="${failed} ${step}"
        elif [ "$step_rc" != "0" ]; then
            echo "RED: fe leg: the ${step} step failed — see above." >&2
            [ "$worst" = "2" ] || worst=1
            failed="${failed} ${step}"
        fi
    done
    echo "  fe leg cost: ${costs} = ${total}s"
    if [ "$worst" != "0" ]; then
        echo "  fe leg:${failed} — exit ${worst}"
    fi
    return "$worst"
}
