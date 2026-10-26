"""The four `--fast` census bodies of `docs_legs.sh`, driven through bash over scratch worlds."""

# deleted: case_all_four_legs_are_wired_into_the_fast_tier — dies with the shim
# pin: test_all_four_legs_run_in_the_fast_mode (registry `Table.mode_legs`)
# deleted: case_the_two_docs_legs_name_the_checkouts_interpreter — dies with the shim
# pin: test_the_two_docs_legs_name_the_checkouts_interpreter_in_the_registry (registry `Leg.argv`)
# does-not-cover: `secrets_scan_changed_files`' branches — only unborn HEAD, staged only.
# does-not-cover: values — ci-env reads KEYS; a wrong endpoint under every key is green here.
# does-not-cover: timing — the bodies are sub-second and the gate prints each leg's wall.
# does-not-cover: a field wrapped across lines — the ADR trigger grammar is per line.
# does-not-cover: deploy/ for the bare-python3 census — those scripts resolve their own.
# does-not-cover: an interpreter invocation built at runtime, in a variable.

# names, never reads: docs/product/in-flight.md — a scratch repo's file (rule 90)

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.djb import registry as R
from quality.djb.legs import dangling_docs
from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives(
    ".env.example",
    ".github/workflows/ci.yml",
    ".github/workflows/nightly-proof.yml",
    "config/",
    "scripts/archaeology_lib.sh",
    "scripts/docs_legs.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_refuse.sh",
    "quality/djb/rituals/publish.py",
    "scripts/secrets_scan.sh",
    "scripts/check.sh",
    "scripts/dangling_paths.py",
    "quality/djb/legs/dangling_docs.py",
)

ROOT = Path(__file__).resolve().parents[2]
LIBRARIES = ("scripts/secrets_scan.sh", "scripts/archaeology_lib.sh", "scripts/docs_legs.sh")

# Halves, so this shipped file spells no whole ghost id or pointer the censuses would catch.
_D, _ADR = "docs/product/", "ADR "
PLANT_ADR = f"{_ADR}zzz-99"
PLANT_REF = f"{_D}zzz_nowhere.md"
REAL_ADR = f"{_ADR}zzz-1"
FORWARD_ADR = f"{_ADR}zzz-98"
TRIGGER_ADR = f"{_ADR}zzz-2"
_ADRS = f"{_D}adrs/"
REAL_FILE = f"{_ADRS}zzz-1.md"
TRIGGER_FILE = f"{_ADRS}zzz-2.md"

Body = Callable[..., Captured]


def _read(run: Captured) -> str:
    return run.path.read_text(errors="replace") if run.path.is_file() else ""


@pytest.fixture
def body(capture: Callable[..., Captured]) -> Body:
    """`body(cwd, script, prelude="")` runs `script` in `cwd` with the three libraries sourced."""

    def run(cwd: Path, script: str, prelude: str = "") -> Captured:
        sources = "".join(f". {lib} || exit 2\n" for lib in LIBRARIES)
        text = f"set -uo pipefail\n{prelude}{sources}cd {str(cwd)!r} || exit 2\n{script}\n"
        return capture(["bash", "-c", text], cwd=ROOT)

    return run


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _unborn(scratch: Path, name: str, homes: bool = True) -> Path:
    """An unborn-HEAD repository: every staged file is the rung's changed set."""
    repo = scratch / name
    (repo / "docs/product").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    if homes:
        _log(repo)
    return repo


def _log(repo: Path) -> None:
    """The decision log: one ADR file, named by its id, headed by it."""
    (repo / _ADRS).mkdir(parents=True, exist_ok=True)
    (repo / REAL_FILE).write_text(f"# {REAL_ADR}\n\n{REAL_ADR} is decided here.\n")
    (repo / "docs/product/architecture.md").write_text("# architecture\n\nthe current state.\n")


def _fresh(scratch: Path) -> Path:
    repo = _unborn(scratch, "repo")
    (repo / "apps/example").mkdir(parents=True)
    (repo / "scripts").mkdir()
    return repo


def _bucketed(scratch: Path) -> Path:
    repo = _unborn(scratch, "bucket", homes=False)
    _log(repo)
    (repo / "docs/product/in-flight.md").write_text("# in flight\n")
    (repo / "docs/product/build-contract.md").write_text("# the build contract\n")
    return repo


def _stage(repo: Path, rel: str, text: str, append: bool = False) -> None:
    path = repo / rel
    with path.open("a" if append else "w") as handle:
        handle.write(text)
    _git(repo, "add", "-A")


def _bucket(body: Body, rel: str) -> str:
    return _read(body(ROOT, f"bucket_for_path {rel!r}")).strip()


# --- the two split censuses, per rung ------------------------------------------------------------


def test_a_planted_unresolvable_adr_cite_in_a_changed_file_reds_fast(
    body: Body, scratch: Path
) -> None:
    repo = _fresh(scratch)
    _stage(
        repo,
        "apps/example/plant.py",
        f'"""A docstring citing {PLANT_ADR}, which resolves nowhere."""\n',
    )
    run = body(repo, "docs_adr_census_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f"adr-census: {PLANT_ADR} resolves nowhere" in out
    assert "apps/example/plant.py" in out

    _stage(repo, "apps/example/plant.py", f'"""A docstring citing {REAL_ADR}, which resolves."""\n')
    run = body(repo, "docs_adr_census_loop")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


def test_a_new_adr_rejection_without_its_trigger_reds_fast(body: Body, scratch: Path) -> None:
    repo = _fresh(scratch)
    _stage(
        repo,
        TRIGGER_FILE,
        f"# {TRIGGER_ADR}\n\n- **{TRIGGER_ADR} (a planted decision)** · context: a plant · "
        "rejected: the other way\n",
    )
    run = body(repo, "docs_adr_census_loop")
    assert run.rc == 1, _read(run)
    assert f"{TRIGGER_ADR} carries rejected: and no trigger to revisit:" in _read(run)

    _stage(
        repo,
        TRIGGER_FILE,
        "  · trigger to revisit: the day the other way is cheaper\n",
        append=True,
    )
    run = body(repo, "docs_adr_census_loop")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


def test_an_adr_file_headed_by_another_id_reds(body: Body, scratch: Path) -> None:
    """The filename is the id: a file whose heading names another id is a finding, never a home."""
    repo = _fresh(scratch)
    _stage(repo, TRIGGER_FILE, f"# {REAL_ADR}\n\nthe wrong heading.\n")
    run = body(repo, "docs_adr_census_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f'adr-census: {TRIGGER_FILE} is headed "# {REAL_ADR}", not "# {TRIGGER_ADR}"' in out

    _stage(repo, TRIGGER_FILE, f"# {TRIGGER_ADR}\n\nthe right heading.\n")
    run = body(repo, "docs_adr_census_loop")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


def test_an_id_resolves_by_its_file_never_by_a_mention(body: Body, scratch: Path) -> None:
    """An id named inside another ADR's file, with no file of its own, still resolves nowhere."""
    repo = _fresh(scratch)
    _stage(repo, REAL_FILE, f"\nsee {PLANT_ADR} for the other half.\n", append=True)
    run = body(repo, "docs_adr_census_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f"adr-census: {PLANT_ADR} resolves nowhere" in out and REAL_FILE in out


def test_no_adr_directory_is_could_not_look(body: Body, scratch: Path) -> None:
    repo = _unborn(scratch, "bare", homes=False)
    _stage(repo, "docs/product/architecture.md", f"# architecture\n\nsee {REAL_ADR}.\n")
    run = body(repo, "docs_adr_census_loop")
    assert run.rc == 2, _read(run)
    assert "the decision log does" in _read(run)


def test_a_rejection_that_moved_verbatim_from_an_old_home_is_not_new(
    body: Body, scratch: Path
) -> None:
    """A paragraph that stood without a trigger in a `docs/product/*.md` at base moves silently."""
    repo = _fresh(scratch)
    para = f"- **{TRIGGER_ADR} (an old decision)** · context: history · rejected: the other way\n"
    _stage(repo, "docs/product/architecture.md", f"\n{para}", append=True)
    _git(repo, "commit", "-q", "-m", "base")
    _stage(repo, "docs/product/architecture.md", "# architecture\n\nthe current state.\n")
    _stage(repo, TRIGGER_FILE, f"# {TRIGGER_ADR}\n\n{para}")
    run = body(repo, "docs_adr_census_loop")
    assert "carries rejected:" not in _read(run), _read(run)


def test_the_adr_directory_ships(body: Body) -> None:
    assert _bucket(body, f"{_ADRS}gate-7.md") == "SHIP"


def test_a_trigger_wrapped_across_lines_is_not_seen(body: Body, scratch: Path) -> None:
    """The per-line grammar, pinned: a `trigger to` / `revisit:` split over two lines is unseen."""
    repo = _fresh(scratch)
    _stage(
        repo,
        TRIGGER_FILE,
        f"# {TRIGGER_ADR}\n\n- **{TRIGGER_ADR} (a planted decision)** · rejected: the other way"
        " · trigger to\n  revisit: the day the other way is cheaper\n",
    )
    run = body(repo, "docs_adr_census_loop")
    assert run.rc == 1, _read(run)
    assert f"{TRIGGER_ADR} carries rejected: and no trigger to revisit:" in _read(run)


def test_a_planted_dangling_docs_pointer_reds_fast(body: Body, scratch: Path) -> None:
    repo = _fresh(scratch)
    _stage(repo, "scripts/plant.sh", f"# see {PLANT_REF} for the argument\n")
    run = body(repo, "docs_dangling_docs_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f"dangling-docs: {PLANT_REF} does not exist" in out
    assert "scripts/plant.sh" in out

    _stage(repo, "scripts/plant.sh", f"# see {_D}architecture.md for the argument\n")
    run = body(repo, "docs_dangling_docs_loop")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


#: A scratch repo's `scripts/` and runbook paths, in halves so this file spells no whole ghost.
_S, _RB = "scripts/", "docs/runbooks/"


# moved: case_a_planted_stale_repository_path_reds_fast — the fast_censuses drive
def test_a_planted_stale_repository_path_reds_fast(body: Body, scratch: Path) -> None:
    repo = _fresh(scratch)
    (repo / "docs/runbooks").mkdir(parents=True)
    _stage(repo, f"{_S}lib.py", "def real():\n    return 1\n")
    _stage(repo, f"{_S}live.sh", f"# lives in {_S}lib.py and {_S}lib.py::real\n")
    _stage(repo, f"{_RB}fenced.md", f"```example\nsee {_S}not_this_tree.py\n```\n")
    run = body(repo, "docs_dangling_docs_loop")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)

    _stage(repo, f"{_S}live.sh", f"# moved to {_S}moved_away.py; see {_S}lib.py::gone\n")
    run = body(repo, "docs_dangling_docs_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f"dangling-paths: {_S}moved_away.py does not exist" in out
    assert f"dangling-paths: {_S}lib.py::gone is defined nowhere" in out
    assert f"{_S}live.sh:1" in out


# moved: case_a_missing_data_file_beside_its_module_is_named_as_the_file — the fast_censuses drive
def test_a_missing_data_file_beside_its_module_is_named_as_the_file(
    body: Body, scratch: Path
) -> None:
    repo = _fresh(scratch)
    _stage(repo, f"{_S}lib.py", "def real():\n    return 1\n")
    _stage(repo, f"{_S}live.sh", f"# the measured {_S}lib.json lives beside it\n")
    run = body(repo, "docs_dangling_docs_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f"dangling-paths: {_S}lib.json does not exist" in out
    assert "::json" not in out


# moved: case_a_stale_directory_before_a_placeholder_reds_fast — the fast_censuses drive
def test_a_stale_directory_before_a_placeholder_reds_fast(body: Body, scratch: Path) -> None:
    repo = _fresh(scratch)
    _stage(repo, f"{_S}lib.py", "def real():\n    return 1\n")
    _stage(repo, f"{_S}live.sh", f"# one module per verb: {_S}<verb>.py\n")
    run = body(repo, "docs_dangling_docs_loop")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)

    _stage(repo, f"{_S}live.sh", f"# one module per verb: {_S}gone/<verb>.py\n")
    run = body(repo, "docs_dangling_docs_loop")
    assert run.rc == 1, _read(run)
    assert f"dangling-paths: {_S}gone/ does not exist" in _read(run)


def _measured_arm() -> set[str]:
    """The three names publish's R12 arm places: the one source, read as its own test reads it."""
    lines = (ROOT / "scripts/archaeology_lib.sh").read_text().splitlines()
    rule = next(line for line in lines if 'hit="$hit R12"' in line)
    return set(re.findall(r"scripts/[a-z_]+\.json", rule))


def test_a_pointer_to_a_measured_file_is_excused_in_a_product_tree(
    body: Body, scratch: Path
) -> None:
    repo = _fresh(scratch)
    measured = sorted(_measured_arm())
    assert len(measured) == 3 and not any((repo / m).exists() for m in measured)
    _stage(repo, f"{_S}lib.sh", "# a product's script\n")
    _stage(repo, "pyproject.toml", "".join(f"# timings live in {m}\n" for m in measured))
    run = body(repo, "docs_dangling_docs_loop")
    out = _read(run)
    assert run.rc == 0 and "VIOLATION" not in out, out
    assert "3 path spelling(s) excused" in out, out

    _stage(repo, "pyproject.toml", f"# timings live in {_S}not_measured.json\n", append=True)
    run = body(repo, "docs_dangling_docs_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f"dangling-paths: {_S}not_measured.json does not exist" in out
    assert "3 path spelling(s) excused" in out, out


def test_the_per_rung_measured_list_is_the_r12_arm(body: Body) -> None:
    from quality.djb import scope
    from quality.djb.legs import pytest_x2

    run = body(ROOT, 'f=$(mktemp)\n_docs_legs_measured "$f" || exit 2\ntr "\\0" "\\n" <"$f"')
    named = set(_read(run).split())
    assert run.rc == 0, _read(run)
    assert named == _measured_arm() == {pytest_x2.DURATIONS, R.WALLS_HOMES[0], scope.MAP_PATH}


def test_an_empty_measured_arm_is_could_not_look(body: Body) -> None:
    run = body(ROOT, 'rules_for() { :; }\nf=$(mktemp)\n_docs_legs_measured "$f"')
    assert run.rc == 2, _read(run)


# moved: case_a_marked_worked_example_is_set_aside_and_the_ledger_around_it_is_judged — the fast_censuses drive  # noqa: E501
def test_a_marked_worked_example_is_set_aside_and_the_ledger_around_it_is_judged(
    body: Body, scratch: Path
) -> None:
    repo = _fresh(scratch)
    (repo / "docs/runbooks").mkdir(parents=True)
    ledger, gone = f"{_RB}ledger.md", f"{_RB}gone.txt"
    _stage(
        repo,
        ledger,
        "# ledger\n\n<!-- worked example — replace with your product's first real entry -->\n\n"
        f"> fixed in {gone}\n\n## next\n\nnothing\n",
    )
    run = body(repo, "docs_dangling_docs_loop")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)

    _stage(repo, ledger, f"\nsee {gone}\n", append=True)
    run = body(repo, "docs_dangling_docs_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f"dangling-paths: {gone} does not exist" in out
    assert f"{ledger}:11" in out and f"{ledger}:5" not in out


def test_unchanged_files_are_not_scanned_per_rung(body: Body, scratch: Path) -> None:
    repo = _fresh(scratch)
    (repo / "apps/example/old.py").write_text(f'"""A docstring citing {PLANT_ADR}."""\n')
    (repo / "scripts/old.sh").write_text(f"# see {PLANT_REF}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _stage(repo, "scripts/new.sh", "# nothing to see\n")

    adr = body(repo, "docs_adr_census_loop")
    dang = body(repo, "docs_dangling_docs_loop")
    assert (adr.rc, dang.rc) == (0, 0), _read(adr) + _read(dang)
    assert "VIOLATION" not in _read(adr) + _read(dang)

    belt = body(
        repo,
        'whole=$(mktemp "${TMPDIR:-/tmp}/djb-whole.XXXXXX")\n'
        'git ls-files -z >"$whole"\n'
        'docs_adr_census "$PWD" "$whole"; a=$?\n'
        'docs_dangling_docs "$PWD" "$whole"; d=$?\n'
        'rm -f "$whole"\necho "rc $a $d"',
    )
    out = _read(belt)
    assert "rc 0 0" in out, out
    assert f"adr-census: {PLANT_ADR} resolves nowhere" in out
    assert f"dangling-docs: {PLANT_REF} does not exist" in out


def _drawer_world(repo: Path) -> None:
    (repo / "apps/example/a.py").write_text(f'"""cites {_D}architecture.md and {PLANT_REF}."""\n')
    (repo / "scripts/b.sh").write_text(
        f"# the drawer {_D}instruments.local.md, again {PLANT_REF}\n# and scripts/zzz_gone.sh\n"
    )
    _git(repo, "add", "-A")


def test_the_python_body_answers_the_shell_body_on_one_world(body: Body, scratch: Path) -> None:
    repo = _fresh(scratch)
    _drawer_world(repo)
    shell = body(
        repo,
        'whole=$(mktemp "${TMPDIR:-/tmp}/djb-whole.XXXXXX")\n'
        'git ls-files -z >"$whole"\n'
        'docs_dangling_docs "$PWD" "$whole" >"$PWD.found"; d=$?\n'
        'rm -f "$whole"\necho "rc $d sites $DOCS_DANGLING_SITES paths $DOCS_DANGLING_PATH_SITES"',
    )
    files = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True
    ).stdout.decode()
    scan = dangling_docs.dangling_docs(repo, files.split("\0"), "the artifact")
    want = f"rc 0 sites {scan.sites} paths {scan.path_sites}"
    assert want in _read(shell), _read(shell)
    assert Path(f"{repo}.found").read_text().splitlines() == scan.findings
    assert f"dangling-docs: {PLANT_REF} does not exist in the artifact" in "\n".join(scan.findings)


def test_the_python_body_exempts_the_drawer_and_counts_it(scratch: Path) -> None:
    repo = _fresh(scratch)
    _drawer_world(repo)
    scan = dangling_docs.dangling_docs(repo, ["apps/example/a.py", "scripts/b.sh"], "the tree")
    assert scan.drawers == 1
    assert not any("instruments.local.md" in f for f in scan.findings)
    assert scan.notes and scan.notes[0].startswith("  1 pointer(s) exempt:")


# --- the bucket filter: a SKELETON ledger's forward citations are vocabulary ----------------------


def test_a_forward_adr_id_in_a_skeleton_ledger_is_set_aside_not_a_finding(
    body: Body, scratch: Path
) -> None:
    skeleton = f"{_D}in-flight.md"
    assert _bucket(body, skeleton) == "SKELETON", "this case has lost its subject"
    repo = _bucketed(scratch)
    _stage(repo, skeleton, f"\n- the next one is {FORWARD_ADR}\n", append=True)
    run = body(repo, "docs_adr_census_loop")
    out = _read(run)
    assert run.rc == 0 and "VIOLATION" not in out, out
    assert re.search(
        r"[0-9]+ ship file\(s\) scanned . [1-9][0-9]* skeleton/trim file\(s\) set aside", out
    ), out

    _stage(repo, skeleton, f"\n- and the plan at {PLANT_REF}\n", append=True)
    run = body(repo, "docs_dangling_docs_loop")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


def test_the_same_forward_adr_id_in_a_ship_file_still_reds(body: Body, scratch: Path) -> None:
    ship = f"{_D}build-contract.md"
    assert _bucket(body, ship) == "SHIP", "this control has lost its subject"
    repo = _bucketed(scratch)
    _stage(repo, ship, f"\n- the next one is {FORWARD_ADR}\n", append=True)
    run = body(repo, "docs_adr_census_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f"adr-census: {FORWARD_ADR} resolves nowhere" in out and ship in out

    run = body(repo, "unset -f bucket_for_path\ndocs_adr_census_loop")
    assert run.rc == 2, _read(run)
    assert "bucket_for_path is not defined" in _read(run)


# --- the byte-identity proof: publish.sh's original bodies against the library ------------------

#: `scripts/publish.sh`'s original leg bodies, verbatim, over a recursive grep of the artifact.
REFERENCE = r"""
ref_legs() {
    local TARGET=$1 h HOMES CITED DOCREFS line id file ref adr_bad dang_bad
    echo ""
    echo "-- adr-census: every ADR id cited in the artifact resolves in the artifact"
    HOMES=$(mktemp "${TMPDIR:-/tmp}/djb-ref-homes.XXXXXX")
    [ -d "$TARGET/$DOCS_ADR_DIR" ] || {
        echo "!! $DOCS_ADR_DIR is not in the artifact" >&2
        rm -f "$HOMES"
        return 2
    }
    for h in "$TARGET/$DOCS_ADR_DIR"/*.md; do
        h=${h##*/}
        [ "$h" = "README.md" ] || echo "ADR ${h%.md}"
    done | LC_ALL=C sort -u >"$HOMES"
    if [ ! -s "$HOMES" ]; then
        rm -f "$HOMES"
        return 2
    fi
    CITED=$(mktemp "${TMPDIR:-/tmp}/djb-ref-cited.XXXXXX")
    (cd "$TARGET" && grep -rIoE "$DOCS_ADR_RE" --exclude-dir=.git . || true) |
        sed 's|^\./||' | LC_ALL=C sort -u >"$CITED"
    adr_bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        id=${line#*:}
        file=${line%%:*}
        if ! grep -qxF "$id" "$HOMES"; then
            echo "   VIOLATION  adr-census: $id resolves nowhere in the artifact — cited in $file"
            adr_bad=$((adr_bad + 1))
        fi
    done <"$CITED"
    echo "   $(LC_ALL=C sort -u -t: -k2 "$CITED" | wc -l | tr -d ' ') citation sites read · \
$(wc -l <"$HOMES" | tr -d ' ') ids resolvable in the ADR directory"
    [ "$adr_bad" -eq 0 ] && echo "   ok — no decision is lost at publish"
    rm -f "$HOMES" "$CITED"

    echo ""
    echo "-- dangling-docs: every docs/ pointer spelled in the artifact resolves in it"
    DOCREFS=$(mktemp "${TMPDIR:-/tmp}/djb-ref-docrefs.XXXXXX")
    (cd "$TARGET" && grep -rIoE "$DOCS_REF_RE" --exclude-dir=.git . || true) |
        sed 's|^\./||' | LC_ALL=C sort -u >"$DOCREFS"
    dang_bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        ref=${line#*:}
        file=${line%%:*}
        [ -f "$TARGET/$ref" ] && continue
        echo "   VIOLATION  dangling-docs: $ref does not exist in the artifact — spelled in $file"
        dang_bad=$((dang_bad + 1))
    done <"$DOCREFS"
    echo "   $(wc -l <"$DOCREFS" | tr -d ' ') pointer sites read"
    [ "$dang_bad" -eq 0 ] && echo "   ok — every docs/ pointer in the artifact resolves inside it"
    rm -f "$DOCREFS"
    return 0
}

new_legs() {
    local TARGET=$1 ART_FILES ADR_OUT DANG_OUT line adr_bad dang_bad rc
    ART_FILES=$(mktemp "${TMPDIR:-/tmp}/djb-new-artfiles.XXXXXX")
    git -C "$TARGET" ls-files -z >"$ART_FILES"

    echo ""
    echo "-- adr-census: every ADR id cited in the artifact resolves in the artifact"
    ADR_OUT=$(mktemp "${TMPDIR:-/tmp}/djb-new-adrout.XXXXXX")
    docs_adr_census "$TARGET" "$ART_FILES" >"$ADR_OUT"
    rc=$?
    [ "$rc" = "2" ] && {
        rm -f "$ART_FILES" "$ADR_OUT"
        return 2
    }
    adr_bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "   VIOLATION  $line"
        adr_bad=$((adr_bad + 1))
    done <"$ADR_OUT"
    echo "   $DOCS_ADR_SITES citation sites read · $DOCS_ADR_IDS ids resolvable in \
the ADR directory"
    [ "$adr_bad" -eq 0 ] && echo "   ok — no decision is lost at publish"
    rm -f "$ADR_OUT"

    echo ""
    echo "-- dangling-docs: every docs/ pointer spelled in the artifact resolves in it"
    DANG_OUT=$(mktemp "${TMPDIR:-/tmp}/djb-new-dangout.XXXXXX")
    docs_dangling_docs "$TARGET" "$ART_FILES" >"$DANG_OUT"
    rc=$?
    [ "$rc" = "2" ] && {
        rm -f "$ART_FILES" "$DANG_OUT"
        return 2
    }
    dang_bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "   VIOLATION  $line"
        dang_bad=$((dang_bad + 1))
    done <"$DANG_OUT"
    echo "   $DOCS_DANGLING_SITES pointer sites read"
    [ "$dang_bad" -eq 0 ] && echo "   ok — every docs/ pointer in the artifact resolves inside it"
    rm -f "$ART_FILES" "$DANG_OUT"
    return 0
}
"""


def test_publish_output_is_byte_identical_after_the_extraction(
    body: Body, scratch_repo: Callable[..., Path], scratch: Path
) -> None:
    repo = scratch_repo("artifact", "artifact")
    for d in ("apps/example", "scripts", "docs/product"):
        (repo / d).mkdir(parents=True)
    _log(repo)
    (repo / "apps/example/a.py").write_text(f'"""cites {REAL_ADR} and {PLANT_ADR}."""\n')
    (repo / "scripts/b.sh").write_text(f"# points at {_D}architecture.md and at {PLANT_REF}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "artifact")
    before, after = scratch / "before.txt", scratch / "after.txt"
    run = body(
        repo,
        f'ref_legs "$PWD" >{str(before)!r} 2>&1; b=$?\n'
        f'new_legs "$PWD" >{str(after)!r} 2>&1; a=$?\necho "rc $b $a"',
        prelude=f'DOCS_LEGS_SCOPE_NOUN="the artifact"\n{REFERENCE}\n',
    )
    assert "rc 0 0" in _read(run), _read(run)
    reference = before.read_text()
    assert "VIOLATION" in reference, "the reference transcript carries no VIOLATION"
    assert after.read_text() == reference


# --- the LOOP_* name census -----------------------------------------------------------------------


# --- the ci-env census ----------------------------------------------------------------------------

BASE_PY = """\
AWS_STORAGE_BUCKET_NAME: str = env.str("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME: str = env.str("AWS_S3_REGION_NAME", default="")
AWS_S3_ENDPOINT_URL: str | None = env.str("AWS_S3_ENDPOINT_URL", default="") or None
AWS_S3_CUSTOM_DOMAIN: str | None = env.str("AWS_S3_CUSTOM_DOMAIN", default="") or None
AWS_ACCESS_KEY_ID: str = env.str("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY: str = env.str("AWS_SECRET_ACCESS_KEY", default="")
AWS_QUERYSTRING_AUTH: bool = env.bool("AWS_QUERYSTRING_AUTH", default=True)
"""
ENV_EXAMPLE = """\
AWS_STORAGE_BUCKET_NAME=
AWS_S3_REGION_NAME=us-east-1
AWS_S3_ENDPOINT_URL=http://127.0.0.1:9000
AWS_S3_CUSTOM_DOMAIN=
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
AWS_QUERYSTRING_AUTH=1
"""
CI_YML = """\
name: gate
on: [push]
env:
  DATABASE_URL: postgres://x
  AWS_S3_ENDPOINT_URL: http://127.0.0.1:9000
  AWS_S3_REGION_NAME: us-east-1
  AWS_ACCESS_KEY_ID: minioadmin
  AWS_SECRET_ACCESS_KEY: minioadmin
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/check.sh
"""
ONE_AUTHORITY_TEST_PY = """\
AWS_STORAGE_BUCKET_NAME = ""
AWS_S3_ENDPOINT_URL = "http://127.0.0.1:9000"
AWS_S3_REGION_NAME = "us-east-1"
AWS_ACCESS_KEY_ID = "minioadmin"
AWS_SECRET_ACCESS_KEY = "minioadmin"  # pragma: allowlist secret — the published compose credential
AWS_SESSION_TOKEN: str | None = None
"""
ONE_AUTHORITY_CI_YML = """\
name: gate
on: [push]
env:
  DATABASE_URL: postgres://x
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
      - name: the gate
        env:
          AWS_ACCESS_KEY_ID: ""
          AWS_SECRET_ACCESS_KEY: ""
          AWS_SESSION_TOKEN: ""
        run: ./scripts/check.sh
"""
DB_LINE = "  DATABASE_URL: postgres://x\n"


def _ci_world(directory: Path, one_authority: bool = False) -> Path:
    """A scratch settings/example/workflow trio; `one_authority` is the platform's own shape."""
    (directory / "config/settings").mkdir(parents=True, exist_ok=True)
    (directory / ".github/workflows").mkdir(parents=True, exist_ok=True)
    (directory / "config/settings/base.py").write_text(BASE_PY)
    (directory / ".env.example").write_text(ENV_EXAMPLE)
    (directory / "config/settings/test.py").write_text(
        ONE_AUTHORITY_TEST_PY if one_authority else 'AWS_STORAGE_BUCKET_NAME = ""\n'
    )
    (directory / ".github/workflows/ci.yml").write_text(
        ONE_AUTHORITY_CI_YML if one_authority else CI_YML
    )
    return directory


def _edit(path: Path, edit: Callable[[str], str]) -> None:
    path.write_text(edit(path.read_text()))


def _drop_lines(path: Path, word: str) -> None:
    _edit(path, lambda t: "".join(x for x in t.splitlines(keepends=True) if word not in x))


def _append(path: Path, text: str) -> None:
    _edit(path, lambda t: t + text)


def test_the_population_carries_the_digit_class(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv")
    run = body(world, "docs_ci_env_leg")
    blind = set(re.findall(r"AWS_[A-Z_]+", (world / "config/settings/base.py").read_text()))
    assert run.rc == 0, _read(run)
    assert (
        "population (4): AWS_ACCESS_KEY_ID AWS_S3_ENDPOINT_URL AWS_S3_REGION_NAME "
        "AWS_SECRET_ACCESS_KEY" in _read(run)
    )
    assert "AWS_S" in blind


def test_a_missing_aws_key_in_ci_env_reds_fast(body: Body, scratch: Path) -> None:
    ci = scratch / "cienv/.github/workflows/ci.yml"
    for key in ("AWS_S3_ENDPOINT_URL", "AWS_SECRET_ACCESS_KEY"):
        world = _ci_world(scratch / "cienv")
        _drop_lines(ci, key)
        run = body(world, "docs_ci_env_leg")
        assert run.rc == 1, _read(run)
        assert f"ci-env: {key} is read from the environment" in _read(run)


def test_no_workflow_file_is_a_printed_skip(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv")
    (world / ".github/workflows/ci.yml").unlink()
    run = body(world, "docs_ci_env_leg")
    out = _read(run)
    assert run.rc == 0 and "SKIP:" in out and "runs no GitHub Actions" in out, out


def test_a_secrets_valued_key_satisfies_the_census(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv")
    _edit(
        world / ".github/workflows/ci.yml",
        lambda t: t.replace(
            "AWS_SECRET_ACCESS_KEY: minioadmin",
            "AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}",
        ),
    )
    run = body(world, "docs_ci_env_leg")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


def test_a_test_settings_pin_of_a_supplied_key_reds(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv")
    _append(world / "config/settings/test.py", 'AWS_S3_ENDPOINT_URL = "http://elsewhere"\n')
    run = body(world, "docs_ci_env_leg")
    assert run.rc == 1 and "pins AWS_S3_ENDPOINT_URL" in _read(run), _read(run)

    _ci_world(world)
    run = body(world, "docs_ci_env_leg")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


def test_one_authority_is_clean_and_an_empty_pin_is_no_supply(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv", one_authority=True)
    run = body(world, "docs_ci_env_leg")
    out = _read(run)
    assert run.rc == 0 and "VIOLATION" not in out, out
    assert "cleared: AWS_SESSION_TOKEN at .github/workflows/ci.yml:14" in out
    assert len(re.findall(r"^  exempt: ", out, re.MULTILINE)) == 4, out


def test_a_second_authority_planted_back_names_both_file_lines(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv", one_authority=True)
    ci = world / ".github/workflows/ci.yml"
    _edit(
        ci, lambda t: t.replace(DB_LINE, DB_LINE + "  AWS_S3_ENDPOINT_URL: http://127.0.0.1:9000\n")
    )
    run = body(world, "docs_ci_env_leg")
    assert run.rc == 1, _read(run)
    assert (
        "AWS_S3_ENDPOINT_URL has TWO authorities — config/settings/test.py:2 and "
        ".github/workflows/ci.yml:5" in _read(run)
    )

    _ci_world(world, one_authority=True)
    _edit(ci, lambda t: t.replace(DB_LINE, DB_LINE + '  AWS_S3_ENDPOINT_URL: ""\n'))
    run = body(world, "docs_ci_env_leg")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


def test_the_platforms_own_tree_has_one_authority(body: Body) -> None:
    run = body(ROOT, "docs_ci_env_leg")
    out = _read(run)
    assert run.rc == 0 and "VIOLATION" not in out, out
    assert len(re.findall(r"^  exempt: ", out, re.MULTILINE)) >= 4, out


def test_an_unparsable_workflow_is_exit_2(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv")
    _append(world / ".github/workflows/ci.yml", "\tAWS_ACCESS_KEY_ID: x\n")
    run = body(world, "docs_ci_env_leg")
    assert run.rc == 2, _read(run)

    _ci_world(world)
    (world / ".github/workflows/ci.yml").write_text(
        "name: x\non: [push]\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: ./scripts/check.sh\n"
    )
    run = body(world, "docs_ci_env_leg")
    assert run.rc == 2, _read(run)


def test_an_empty_population_is_exit_2(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv")
    (world / "config/settings/base.py").write_text("# no AWS reads at all\n")
    run = body(world, "docs_ci_env_leg")
    assert run.rc == 2 and "population is EMPTY" in _read(run), _read(run)


def test_a_non_aws_read_whose_example_differs_reds(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv")
    _append(
        world / "config/settings/base.py",
        'EMAIL_PORT: int = env.int("EMAIL_PORT", default=25)\n'
        'POOL_TIMEOUT: float = env.float("POOL_TIMEOUT", default=10.0)\n',
    )
    _append(world / ".env.example", "EMAIL_PORT=1025\nPOOL_TIMEOUT=10\n")
    run = body(world, "docs_ci_env_leg")
    out = _read(run)
    assert run.rc == 1 and "ci-env: EMAIL_PORT is read from the environment" in out, out
    assert "POOL_TIMEOUT" not in out

    _edit(
        world / ".github/workflows/ci.yml",
        lambda t: t.replace(DB_LINE, DB_LINE + '  EMAIL_PORT: "1025"\n'),
    )
    run = body(world, "docs_ci_env_leg")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


def test_a_non_literal_default_counts_as_different(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv")
    _append(
        world / "config/settings/base.py",
        'FROM: str = env.str("FROM", default="a@b")\n'
        'SERVER_EMAIL: str = env.str("SERVER_EMAIL", default=FROM)\n',
    )
    _append(world / ".env.example", "FROM=a@b\nSERVER_EMAIL=a@b\n")
    run = body(world, "docs_ci_env_leg")
    out = _read(run)
    assert run.rc == 1 and "ci-env: SERVER_EMAIL is read from the environment" in out, out
    assert "ci-env: FROM is read" not in out


def test_every_workflow_that_runs_the_stack_is_censused(body: Body, scratch: Path) -> None:
    world = _ci_world(scratch / "cienv")
    (world / ".github/workflows/nightly.yml").write_text(
        "name: nightly\non: [workflow_dispatch]\nenv:\n  DATABASE_URL: postgres://x\njobs:\n"
        "  proof:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: ./scripts/ci_stack.sh up db\n"
    )
    (world / ".github/workflows/labels.yml").write_text(
        "name: labels\non: [issues]\nenv:\n  GH_TOKEN: x\njobs:\n  label:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: echo label\n"
    )
    run = body(world, "docs_ci_env_leg")
    out = _read(run)
    assert run.rc == 1, out
    assert "under no env: map in .github/workflows/nightly.yml" in out
    assert "under no env: map in .github/workflows/ci.yml" not in out
    assert "not censused: .github/workflows/labels.yml runs neither" in out


def test_the_platforms_own_population_carries_the_four_names(body: Body) -> None:
    run = body(ROOT, "docs_ci_env_leg")
    out = _read(run)
    population = re.search(r"^  population \(.*$", out, re.MULTILINE)
    assert run.rc == 0 and population, out
    words = set(population.group(0).split())
    assert {"BRAND_ACCENT", "EMAIL_HOST", "EMAIL_PORT", "SERVER_EMAIL"} <= words
    assert re.search(r"^  read: ", out, re.MULTILINE)
    assert re.search(r"^  \.github/workflows/nightly-proof\.yml: ", out, re.MULTILINE)


# --- the wiring, read from the registry -----------------------------------------------------------


def test_all_four_legs_run_in_the_fast_mode() -> None:
    fast = {leg.name for leg in R.load(ROOT).mode_legs("fast")}
    assert {"adr-census", "dangling-docs", "ci-env"} <= fast
    assert "loop-names" not in fast


def test_the_two_docs_legs_name_the_checkouts_interpreter_in_the_registry() -> None:
    table = R.load(ROOT)
    for leg, script in (
        ("goalpost-census", "scripts/goalpost_scan.py"),
        ("queue-index", "scripts/queue_index.py"),
    ):
        argv = table.leg(leg).argv
        assert ("<checkout python>", script) in {a[:2] for a in argv}, (leg, argv)


# --- the interpreter every shipped python file runs under -----------------------------------------

_BARE_PYTHON3 = re.compile(
    r"(^|[^-A-Za-z0-9_./])python3\s+(\"?\$\{?[A-Za-z_]|\"?[A-Za-z0-9_./-]*\.py)"
)


def test_no_shipped_python_file_is_run_by_a_bare_python3() -> None:
    files = [
        *sorted((ROOT / "scripts").glob("*.sh")),
        *sorted((ROOT / "scripts/githooks").glob("*")),
        *sorted((ROOT / "scripts/tests").glob("*.sh")),
    ]
    offenders = []
    for path in (f for f in files if f.is_file()):
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if _BARE_PYTHON3.search(line.split("#", 1)[0]):
                offenders.append(f"{path.name}:{number}")
                break
    assert not offenders, (
        f"these run a shipped python file on whatever python3 is first: {offenders}"
    )


def test_publish_sources_the_library_and_names_no_second_body() -> None:
    publish = (ROOT / "quality/djb/rituals/publish.py").read_text()
    assert re.search(r"scripts/docs_legs\.sh", publish)
    assert not re.search(r"ADR \[a-z0-9\]|docs/\[A-Za-z0-9", publish)


@pytest.mark.parametrize("page", ["docs/sdk/sending-messages.md", "docs/sdk/live-updates.md"])
def test_a_guide_s_pointers_and_links_resolve(page: str) -> None:
    scan = dangling_docs.dangling_docs(ROOT, [page], "this tree")
    assert scan.findings == [] and scan.path_sites > 0, (scan.findings, scan.path_sites)
    links = re.findall(r"\]\(([\w.-]+\.md)\)", (ROOT / page).read_text())
    assert links and [link for link in links if not (ROOT / "docs/sdk" / link).is_file()] == []


# --- a shipped pointer into a class the export trims ---------------------------------------------


def test_a_changed_shipped_file_pointing_into_a_trimmed_class_reds_fast(
    body: Body, scratch: Path
) -> None:
    repo = _fresh(scratch)
    for kept in (f"{_D}reports/x/held.md", f"{_D}skeletons/held.md", f"{_D}archive/held.md"):
        (repo / kept).parent.mkdir(parents=True, exist_ok=True)
        (repo / kept).write_text("# held here, trimmed from every artifact\n")
    _stage(repo, "apps/example/cites.py", f'"""See {_D}reports/x/held.md."""\n')
    run = body(repo, "docs_dangling_docs_loop")
    out = _read(run)
    assert run.rc == 1, out
    assert f"dangling-docs: {_D}reports/x/held.md is trimmed from every artifact (TRIM)" in out

    _stage(repo, "apps/example/cites.py", f'"""See {_D}skeletons/held.md."""\n')
    out = _read(body(repo, "docs_dangling_docs_loop"))
    assert f"{_D}skeletons/held.md is trimmed from every artifact (SKELETON-SOURCE)" in out

    _stage(repo, "apps/example/cites.py", f'"""See {_D}archive/held.md."""\n')
    run = body(repo, "docs_dangling_docs_loop")
    assert run.rc == 0 and "VIOLATION" not in _read(run), _read(run)


def test_no_shipped_file_points_into_a_class_the_export_trims() -> None:
    """The whole ship-set as the export classes it: every pointer resolves in the artifact."""
    from quality.djb.rituals import publish

    found = publish.census(ROOT)
    scan = dangling_docs.dangling_docs(
        ROOT,
        found.ship,
        "the artifact",
        found.trim + found.source,
        found.placed.get("R12", []),
    )
    assert scan.sites and scan.path_sites, scan
    assert not scan.findings, "\n".join(scan.findings)
