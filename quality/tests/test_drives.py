"""One test per tracked drive: run it, and judge it by its exit and its one summary line."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.drives import (
    drive_name,
    header_line,
    params,
    population,
    require_alone,
    require_declared,
    run_drive,
    verdict,
)

pytestmark = pytest.mark.drives("quality/tests/drives.py")

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("drive", list(params(ROOT)))
def test_drive(drive: str, scratch: Path, request: pytest.FixtureRequest) -> None:
    """The drive exits 0 with a summary that counts no failure."""
    require_declared(request.node, drive)
    require_alone(ROOT / drive)
    sink = scratch / "drive.out"
    rc, took = run_drive(ROOT / drive, ROOT, sink)
    output = sink.read_text(errors="replace")
    code, why = verdict(rc, output, Path(drive).stem)
    results = request.config.getoption("drives_results")
    if results:
        Path(results, f"{drive_name(drive)}.out").write_text(output)
        Path(results, f"{drive_name(drive)}.done").write_text(f"{code} {took}\n")
    if code == 2:
        raise CouldNotLook(f"{drive}: {why}")
    assert code == 0, f"{drive}: {why}\n" + "\n".join(output.splitlines()[-40:])


# The census's forms are closed; a target is `$ROOT`, `${ROOT}` or a top-level name derived from it.
# does-not-cover: a path built by concatenation, a relative write after `cd "$ROOT"`.
# does-not-cover: a helper the drive sources, and `rm`/`touch`/`ln`/`sed -i` writes.
# does-not-cover: the checkout held under a name other than `ROOT`.
# does-not-cover: a later top-level `ROOT=` rebind excuses the writes above it.
CHECKOUT_ROOT = re.compile(
    r'^ROOT="?(?:\$PWD|\$\(pwd(?: -P)?\)|\$\(git rev-parse --show-toplevel\))"?\s*$'
)
TOP_ROOT = re.compile(r"^ROOT=")
DERIVED = re.compile(r'^([A-Za-z_]\w*)="?\$\{?(\w+)\}?(?:[/"]|$)')
SUBSTITUTION = re.compile(r"\$\([^()]*\)")
GIT_WRITES = (
    "add|am|apply|checkout|cherry-pick|clean|commit|merge|mv|rebase|reset|restore|revert|rm|stash"
    "|switch|update-index"
)


def _rooted(names: set[str]) -> str:
    """A pattern for `$name` or `${name}`, optionally quoted, over the given names."""
    alt = "|".join(sorted(names))
    return rf'"?\$(?:\{{(?:{alt})\}}|(?:{alt})\b)'


def checkout_writes(text: str) -> list[tuple[int, str]]:
    """Each `(line, form)` where the drive writes under the checkout it runs in."""
    lines = text.splitlines()
    tops = [line for line in lines if TOP_ROOT.match(line)]
    if not tops or not CHECKOUT_ROOT.match(tops[-1]):
        return []
    names = {"ROOT"}
    for line in lines:
        derived = DERIVED.match(line)
        if derived and derived.group(2) in names:
            names.add(derived.group(1))
    rooted = _rooted(names)
    forms = {
        "redirect": re.compile(rf"(?<![<>&])>>?\s*{rooted}"),
        "mkdir/tee": re.compile(rf"\b(?:mkdir|tee)\b[^;|&]*\s{rooted}"),
        "git": re.compile(rf"\bgit\s+-C\s+{rooted}\"?\s+(?:{GIT_WRITES})\b"),
    }
    last_arg = re.compile(rf"^{rooted}")
    found = []
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            continue
        flat = SUBSTITUTION.sub("SUB", SUBSTITUTION.sub("SUB", line))
        found += [(number, form) for form, pattern in forms.items() if pattern.search(flat)]
        for command in re.split(r"[;|&]+", flat):
            words = command.split()
            if len(words) > 2 and words[0] in ("cp", "mv") and last_arg.match(words[-1]):
                found.append((number, "cp/mv"))
    return found


def test_a_drive_that_writes_under_the_checkout_declares_serial() -> None:
    """Every drive the census sees writing under the checkout declares `# serial:` in its header."""
    unserial = []
    for drive in population(ROOT):
        writes = checkout_writes((ROOT / drive).read_text(errors="replace"))
        if writes and header_line(ROOT / drive, "serial") is None:
            sites = ", ".join(f":{n} {form}" for n, form in writes[:3])
            unserial.append(f"{drive} ({sites})")
    forms = "redirect · cp/mv (last argument) · mkdir/tee · git -C <root> <write>"
    assert not unserial, f"no `# serial:` line, census forms [{forms}]:\n" + "\n".join(unserial)


@pytest.mark.parametrize(
    "body",
    [
        'printf x >>"${ROOT}/apps/a.py"\n',
        'cp "$WORK/a" "$ROOT/apps/a.py"\n',
        'mkdir -p "${ROOT}/apps/x"\n',
        'PLANT="${ROOT}/apps/a.py"\nprintf x >"$PLANT"\n',
        'git -C "$ROOT" stash\n',
    ],
)
def test_the_census_names_each_form(body: str) -> None:
    """Each census form, planted in a drive rooted at `$PWD`, is named."""
    assert checkout_writes('ROOT="$PWD"\n' + body)


@pytest.mark.parametrize(
    "text",
    [
        'ROOT="$PWD"\ncp "$ROOT/apps/a.py" "$WORK/a"\ncp "$(dirname "$ROOT/x")/b.sh" "$d/b.sh"\n',
        'ROOT="$(cd "$WORK" && pwd -P)/checkout"\nprintf x >"${ROOT}/apps/a.py"\n',
    ],
)
def test_the_census_is_silent_on_reads_and_mirrors(text: str) -> None:
    """A read of the checkout, or a write into a mirror rebound to `ROOT`, is not counted."""
    assert checkout_writes(text) == []
