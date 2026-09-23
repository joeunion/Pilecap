#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. A wrong
# shell here does not crash; it ANSWERS, and the answer looks like the tree's
# fault. The two tests below are `test_secrets_scan.sh`'s, for its measured
# reason: on macOS `/bin/sh` IS bash, so only POSIX MODE tells `sh x.sh` from
# `bash x.sh`, while on Linux `/bin/sh` is dash and the first test is the one
# that fires. Neither test alone covers both machines.
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
# census: cross-app it classifies every script under scripts/ that depends on a local main, so its subject is the whole shell population and no scope narrows it; no organs
# drives: docs/product/instruments.md scripts/
# cites: docs/product/instruments.local.md
# THE CROSS-APP CENSUS OVER THE SHELL POPULATION.
#
#   ./scripts/tests/test_scripts_census.sh          run every case
#   ./scripts/tests/test_scripts_census.sh --list   name them and stop
#
# WHY IT IS ITS OWN DRIVE, AND WHY IT IS MARKED. A census quantifies over a
# whole population — here every `scripts/*.sh` — so its subject is the tree and
# not a rung. The `--loop` narrows the suite to the apps a rung touched, and
# narrowing what a CENSUS is about is the one thing a scope must never do: a
# new script that starts depending on a local `main` is exactly the change a
# narrow loop would not be looking at. The marker at the top of this file is
# how it says so; the `--loop`'s always-on leg reads it and runs this drive at
# every scope, whatever its price. The same grammar marks a pytest module at
# the pytest door's own always-on derivation, and one reader
# (`loop_scope__declared_censuses`) answers for both.
#
# WHERE IT CAME FROM. `case_the_siblings_census_names_every_script_that_depends_on_a_local_main`
# lived in `scripts/tests/test_setup_env.sh`, which is a drive about ONE
# script's env-sync step and runs only at the bank. The census inside it was
# about the whole of `scripts/` and ran only at the bank with it. The case moved
# here with its own text and its own name; `test_setup_env.sh --list` no longer
# names it and this drive's `--list` does.
#
# NO ORGANS, and that is part of the declaration above: git is not called, no
# database is opened, no docker is touched and nothing leaves this machine. A
# census joined to every `--loop` that needed an organ would be a per-rung gate
# answering 2 on any machine without one.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * A DEPENDENCY SPELLED SOME OTHER WAY. The pattern is four alternatives and
#     it is the blind spot: a script reaching a local `main` through a variable,
#     a helper or a spelling nobody has written yet is invisible here until a
#     miss names it. Two of the four alternatives are in the pattern BECAUSE a
#     field test found the census missing its loudest member.
#   * WHETHER A CLASSIFICATION IS RIGHT. This asserts that every member HAS one
#     and that three named members are still in the population; whether
#     `ASSUMES` is the honest verdict for a given script is a reader's
#     judgement, made once, beside the name.
#   * EVERY OTHER SCRIPTS-WIDE PROPERTY. This drive holds two censuses today. It
#     is the home for the next one rather than a reason to start a third file.
#   * WHETHER THE INSTRUMENT CENSUS'S POPULATION IS RIGHT. The second census
#     below asks whether the product's own document is READ, not whether the
#     derivation is complete; `scripts/goalpost_scan.py --selftest` owns that
#     half, and — declared rather than discovered — no moment runs it.

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_scripts_census: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's writes inside its own" >&2
    echo "   scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
# `checkout_python` — the one reader of this checkout's interpreter, used by the
# second census below. Sourced here rather than inside the case so a missing
# library is a refusal at the top of the drive and not halfway through it.
# shellcheck source=scripts/gate_refuse.sh
. scripts/gate_refuse.sh

# Section 5 of the preamble, opted into: on bash 3.2 a `set -u` death hands the
# EXIT trap a status of 0, so a drive that dies halfway reads as a PASS.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_scripts_census: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

# >>> one case, by name >>>
# `--case <name>` runs exactly that case and nothing else. The seam exists so
# rule 60's drawer census can prove ONE PLANT PER DRAWER through the drive that
# already owns the property, rather than re-implementing the drawer's reader —
# a second implementation of a reader is a second opinion about it. A name this
# file does not define is exit 2, never a silent run of nothing.
ONLY_CASE=""
run_case() {
    [ -z "$ONLY_CASE" ] || [ "$1" = "$ONLY_CASE" ] || return 0
    "$@"
}
# <<< one case, by name <<<
case "${1:-}" in
"") ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
--case)
    [ -n "${2:-}" ] || {
        echo "!! --case needs a case name; --list names them" >&2
        exit 2
    }
    grep -q "^${2}() {" "$0" || {
        echo "!! --case: test_scripts_census.sh defines no case named '${2}'; --list names them" >&2
        exit 2
    }
    ONLY_CASE="$2"
    ;;
*)
    echo "!! unknown argument '$1': test_scripts_census.sh takes nothing, --list or --case <name>" >&2
    exit 2
    ;;
esac

[ -d scripts ] || cannot_look "there is no scripts/ directory here — the population this drive censuses is not in this tree"

ROOT="$PWD"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-scripts-census-drive.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# THE SECOND CENSUS'S PROBE, WRITTEN OUT RATHER THAN INLINED. A here-document
# inside a `$( )` is parsed by the OUTER shell, so a backtick or an apostrophe
# in the Python below becomes a command substitution the case never wrote —
# it cost this drive two syntax errors before the file moved out here. It
# lives in the scratch directory, never beside the tree it measures.
CENSUS_PROBE_PY="${WORK}/census_probe.py"
cat >"$CENSUS_PROBE_PY" <<'PY'
import re
import sys

sys.path.insert(0, "scripts")
import goalpost_scan as g

doc = g._read(g.CENSUS)


def rows(row):
    return (
        "| Instrument | Fails loud? | Says what it saw? | States its blind spots? | Finding |\n"
        "|---|---|---|---|---|\n" + row + "\n"
    )


cite = "(x/y.sh:1)"
ghost_row = f"| `zz/not/a/file.sh` | yes {cite} | loud {cite} | yes {cite} | none |"
# THE DUPLICATE IS TAKEN FROM THE DOCUMENT rather than typed: a path spelled
# here would be a second place that knows what the census carries, and the
# `# drives:` declaration at the top of this file would then have to cover a
# file whose BYTES this case does not depend on at all.
first = g.read_table(doc, "Instrument", "instruments.md")[0][0]
dupe_path = re.search(r"`([^`]+)`", first).group(1)
dupe_row = f"| `{dupe_path}` | yes {cite} | loud {cite} | yes {cite} | none |"

# (1) READ AT ALL: a row for a path that is not in the population is a ghost,
# and a ghost is exit 2. A local document nothing opened would be exit 0.
code, lines = g.census(doc, rows(ghost_row))
text = "\n".join(lines)
if code != 2 or "censused but not an instrument" not in text or "zz/not/a/file.sh" not in text:
    print(f"BAD read: exit {code}; the local row was not judged\n{text}")
    raise SystemExit(1)
if f"1 product row(s) in {g.CENSUS_LOCAL.name}" not in text:
    print(f"BAD read: the run does not say how many product rows it read\n{text}")
    raise SystemExit(1)

# (2) ONE HOME PER PATH.
try:
    g.census(doc, rows(dupe_row))
except g.CannotLook as e:
    if dupe_path not in str(e) or g.CENSUS.name not in str(e):
        print(f"BAD duplicate: refused without naming the path and the file: {e}")
        raise SystemExit(1)
else:
    print("BAD duplicate: a path claimed by both documents was not refused")
    raise SystemExit(1)

# (3) ABSENT IS FREE, asserted by comparing the two renderings.
a = g.census(doc)
b = g.census(doc, None)
if a != b:
    print("BAD absent: the default and an explicit None disagree")
    raise SystemExit(1)
if any(g.CENSUS_LOCAL.name in line for line in a[1]):
    print("BAD absent: the census names the local document on a tree that has none")
    raise SystemExit(1)

print(f"ok {g.CENSUS_LOCAL.name}: read, one home per path, absent is byte-identical")
PY

CURRENT=""
ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    FAILED=$((FAILED + 1))
}

# --- the census, as a function over a root -----------------------------------
#
# ONE BODY, TWO CALLERS, AND THAT IS WHAT MAKES THE PLANT POSSIBLE. The first
# case runs it over this checkout — which is the census, and the reason the file
# exists. The second runs it over a scratch COPY of `scripts/` with an
# unclassified dependent planted in it, and requires the same body to red.
# Without the second, this file is a census nobody has ever seen fail, which is
# the shape rung-execution §2 exists to refuse.
#
# THE PATTERN CARRIES `--hard main`, and that is not decoration. V-F's finding 2
# (2026-09-14): the census as first written — `refs/heads/main\|branch main` —
# returned SIX files and `rung_start.sh` was not among them, because the
# strongest dependency in the tree is spelled `git reset --hard main` and
# matches neither alternative. A census that misses its loudest member is a
# census that was never measured against its own population.
#
# AND IT CARRIES `rev-parse main` FOR THE SAME REASON, one member later.
# `scripts/verifier_box.sh` joined this census by the `refs/heads/main` in its
# push — which is a DESTINATION ref name and no dependency at all, since what
# that push sends is HEAD — while its real dependency is spelled
# `git rev-parse main` in the bake, where the image's name comes from. The first
# three alternatives match the harmless line and miss the load-bearing one: a
# later rung tidying the push would have dropped the whole file out of the
# census with the dependency still in it. Measured when the spelling was added:
# the census returns the same seven files either way, so the alternative buys
# the next member rather than this one.
CENSUS_PATTERN='refs/heads/main\|branch main\|--hard main\|rev-parse main'

# census_verdict <path> — the classification for a member, or nothing at all
# when this census has never decided about it.
census_verdict() {
    case "${1##*/}" in
    setup.sh) printf '%s' "CREATES — this step, the only one in the tree that makes the ref" ;;
    verify_start.sh) printf '%s' "CREATES — at the verified sha, in its own clone" ;;
    loop_tier.sh) printf '%s' "REFUSES — exit 2 naming both legal moves when the ref is absent" ;;
    secrets_scan.sh) printf '%s' "ASSUMES — merge-base basis, SECRETS_SCAN_BASE_REF overridable" ;;
    gate_ledger.sh) printf '%s' "ASSUMES — guarded: rev-parse first, then 'no-merge-base'" ;;
    rung_start.sh) printf '%s' "ASSUMES — \`git reset --hard main\` unguarded; a checkout without the ref gets git's own status through act_failed" ;;
    verifier_box.sh) printf '%s' "REFUSES — exit 2 in bake's pre-launch block, naming both legal moves: the image is NAMED after the ref and the push sends HEAD" ;;
    *) printf '%s' "" ;;
    esac
}

# census_members <scripts dir> — every member of the population, sorted.
census_members() {
    grep -rl -- "$CENSUS_PATTERN" "$1"/*.sh 2>/dev/null | sort
}

# census_unclassified <scripts dir> — every member this census has not decided
# about, one per line. EMPTY IS THE ONLY GREEN ANSWER.
census_unclassified() {
    local f
    for f in $(census_members "$1"); do
        [ -n "$(census_verdict "$f")" ] || printf '%s\n' "$f"
    done
}

case_the_siblings_census_names_every_script_that_depends_on_a_local_main() {
    # `ensure_local_main` exists because every other script here that reads
    # `refs/heads/main` by name is a script that cannot make one. That
    # population is the reason the step is in `setup.sh` at all, so it is
    # censused rather than listed in prose: a new script that starts depending
    # on a local `main` and is not classified here is one more caller nobody
    # decided about.
    CURRENT="every script depending on a local main is classified"
    local files f verdict
    files="$(census_members "${ROOT}/scripts")"
    if [ -z "$files" ]; then
        bad "the census matched NO script at all — a grep that found nothing is not a tree with nothing in it"
        return
    fi
    echo "           census: $(printf '%s' "$files" | sed 's|.*/||' | tr '\n' ' ')"
    for f in $files; do
        verdict="$(census_verdict "$f")"
        if [ -n "$verdict" ]; then
            ok "${f##*/}: ${verdict}"
        else
            bad "${f##*/} depends on a local main and this census does not classify it — decide whether it refuses, creates or assumes"
        fi
    done
    # THE MEMBER THE OLD PATTERN MISSED, named so that narrowing the pattern
    # back reds here rather than going quietly green over five files.
    case "$files" in
    *scripts/rung_start.sh*) ok "scripts/rung_start.sh is IN the census — the pattern still carries \`--hard main\`" ;;
    *) bad "scripts/rung_start.sh is not in the census, and it resets --hard to main — the pattern has narrowed back" ;;
    esac
    case "$files" in
    *scripts/loop_tier.sh*) ok "scripts/loop_tier.sh is still in it — the refusal this step exists to stop a stranger hitting" ;;
    *) bad "scripts/loop_tier.sh dropped out of the census — the refusal that motivates the whole step" ;;
    esac
    # THE MEMBER WHOSE DEPENDENCY THE PATTERN NEARLY MISSED, asserted twice —
    # once that the file is still censused, once that the spelling its bake
    # actually uses is still one of the alternatives. The second is the one that
    # survives a tidy-up of the push line.
    case "$files" in
    *scripts/verifier_box.sh*) ok "scripts/verifier_box.sh is in the census — the bake that names an image after the ref" ;;
    *) bad "scripts/verifier_box.sh dropped out of the census, and its bake still reads a local main to name the image it captures" ;;
    esac
    case "$CENSUS_PATTERN" in
    *'rev-parse main'*) ok "the pattern carries \`rev-parse main\` — the bake's spelling, which the other three alternatives do not match" ;;
    *) bad "the pattern no longer carries \`rev-parse main\`: a script whose only dependency is spelled that way falls out of this census entirely" ;;
    esac
}

case_an_unclassified_dependent_reds() {
    # THE CANARY. A census whose failing direction nobody has ever seen is a
    # census that may be unable to fail — and this one's failing direction is
    # silent by construction, because it fires on a file that does not exist
    # yet. So the plant builds one: a scratch copy of `scripts/`, a new script
    # that depends on a local `main` in the loudest spelling there is, and the
    # same classifier the case above uses.
    CURRENT="an unclassified dependent reds the census"
    local dir="${WORK}/scripts" unclassified
    mkdir -p "$dir"
    cp "${ROOT}"/scripts/*.sh "$dir"/ 2>/dev/null || true
    unclassified="$(census_unclassified "$dir")"
    if [ -n "$unclassified" ]; then
        bad "the scratch copy of scripts/ is ALREADY unclassified before the plant: $(printf '%s' "$unclassified" | tr '\n' ' ') — the plant below would prove nothing"
        return
    fi
    ok "the scratch copy of scripts/ starts with every member classified"

    printf '#!/usr/bin/env bash\n# a planted dependent\ngit reset --hard main\n' >"${dir}/zz_planted_dependent.sh"
    unclassified="$(census_unclassified "$dir")"
    case "$unclassified" in
    *zz_planted_dependent.sh*)
        ok "the planted dependent is NAMED as unclassified: $(printf '%s' "$unclassified" | tr '\n' ' ')"
        ;;
    *)
        bad "a script spelling \`git reset --hard main\` was planted and the census did not name it (it said: '${unclassified}') — the census cannot fail"
        return
        ;;
    esac

    rm -f "${dir}/zz_planted_dependent.sh"
    unclassified="$(census_unclassified "$dir")"
    if [ -n "$unclassified" ]; then
        bad "the plant was removed and the census still names '${unclassified}' — it is not reading the tree it is given"
    else
        ok "the plant removed, the census is silent again — both directions driven"
    fi
}

case_the_marker_is_the_one_grammar_the_loop_reads() {
    # THE MARKER IS WHY THIS DRIVE RUNS AT ALL, and a marker nothing checks is a
    # declaration that can be reworded out of the population it joined. The
    # constant is read out of the library that reads it rather than spelled
    # here — a drive that spelled the marker would itself carry one.
    CURRENT="the marker this file declares is the one the loop reads"
    local marker head
    if [ ! -r "${ROOT}/scripts/loop_tier.sh" ]; then
        bad "scripts/loop_tier.sh is not in this tree — the reader of this file's marker is gone"
        return
    fi
    marker="$(awk -F"'" '/^LOOP_SCOPE_CENSUS_MARKER=/ { print $2; exit }' "${ROOT}/scripts/loop_tier.sh")"
    if [ -z "$marker" ]; then
        bad "scripts/loop_tier.sh declares no LOOP_SCOPE_CENSUS_MARKER — nothing reads this file's declaration"
        return
    fi
    head="$(sed -n '1,40p' "$0")"
    case "$head" in
    *"${marker} "*) ok "this file carries \`${marker}\` with a reason, in its first 40 lines" ;;
    *) bad "this file does not carry \`${marker}\` where the reader looks — it would run at the bank only, which is where it came from" ;;
    esac
}

# --- the SECOND census: the product's own instrument document ----------------
#
# WHY IT IS HERE. The instrument census (`goalpost_scan.py --census`, the
# `goalpost-census` leg of `--fast`) refuses an executable with no row, and on a
# PRODUCT that population includes every script the product wrote — so until the
# drawer existed, a product owed rows in `docs/product/instruments.md`, a
# template-owned file, and paid for that edit at every release. The drawer is
# `docs/product/instruments.local.md`, read beside the template's by the same one
# reader.
#
# WHAT THIS CASE DRIVES, AND WHAT IT DELIBERATELY DOES NOT. It calls the SHIPPED
# `census()` — imported, never copied — with a planted local DOCUMENT and no
# planted file, so it needs no organ, no git and no plant inside the checkout
# this drive runs in. The other half, a planted EXECUTABLE joining the derived
# population, is `goalpost_scan.py --selftest`'s own drawer canaries, because
# that plant is an untracked `+x` in the real tree and belongs nowhere near an
# always-on member of `--loop`.
#
# THE THREE ARMS ARE THE THREE WAYS THIS CAN GO WRONG SILENTLY: a local document
# that is not read at all (its rows would be neither honoured nor refused), a
# path claimed by both documents (two rows, one path, disagreeing the day either
# is edited), and an absent drawer that is not free (every product-less tree
# paying for a feature it does not use).
case_the_product_census_document_is_read_beside_the_templates() {
    CURRENT="the product's own instruments document is read beside the template's"
    local out rc=0 py=""
    # THE CHECKOUT'S INTERPRETER FIRST, and a PATH one only as a stated
    # fallback. `test_fast_censuses.sh::case_no_shipped_python_file_is_run_by_a_bare_python3`
    # is the census that asks for this, and its reason is dependencies: a
    # shipped module run on whatever is first on PATH is a module running
    # against somebody else's installed set. The probe imports
    # `scripts/goalpost_scan.py`, which is stdlib-only by its own docstring —
    # so a checkout with no venv is still a tree this case can judge, and
    # falling back is a smaller lie than answering could-not-look on one.
    py="$(checkout_python "$ROOT" 2>/dev/null || true)"
    [ -n "$py" ] || py="$(command -v python3 || true)"
    if [ -z "$py" ]; then
        bad "no python at all — neither this checkout's .venv nor one on PATH; the instrument census is a Python reader and this case cannot look"
        return
    fi
    out="$("$py" "$CENSUS_PROBE_PY" 2>&1)" || rc=$?
    if [ "$rc" != "0" ]; then
        bad "the product census document is not read the way it is documented: $(printf '%s' "$out" | tr '\n' '|')"
        return
    fi
    ok "${out}"
}

run_case case_the_siblings_census_names_every_script_that_depends_on_a_local_main
run_case case_an_unclassified_dependent_reds
run_case case_the_marker_is_the_one_grammar_the_loop_reads
run_case case_the_product_census_document_is_read_beside_the_templates

echo "test_scripts_census: ${PASSED} passed · ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another case —
# see section 5 of the preamble for why saying so is load-bearing.
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! a script under scripts/ depends on a local \`main\` and nobody has decided" >&2
    echo "   what it does about one — or the census that would have said so has" >&2
    echo "   narrowed. Both failures are silent in the ordinary course: the caller" >&2
    echo "   works on every machine that has the ref and refuses, resets or assumes" >&2
    echo "   on the first one that does not." >&2
    exit 1
fi
