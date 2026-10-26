"""The release road: fetch, census, merge, fold, SDK step, base, gate — each with its `next:`."""

# does-not-cover: a conflict outside `max_migration.txt` — named with its file, resolved by hand.
# does-not-cover: what a step's red means — its line is the step's own, and the log has the rest.

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from quality.djb.rituals.divergence import TEMPLATE_BASE_DRAWER
from quality.djb.rituals.feature import (
    Ran,
    Runner,
    Step,
    err,
    first_red,
    out,
    piped,
    python,
    run_step,
)

ROOT = Path(__file__).resolve().parents[3]
CENSUS = "./scripts/divergence_census.sh"
NO_SDK = "unknown argument '--sdk'"
MIGRATION_LEAF = "migrations/max_migration.txt"
LOCKS = ("uv.lock", "frontend/pnpm-lock.yaml")
_PNPM_PIN = re.compile(r"^  '?((?:@[^/\s']+/)?[^@\s']+)@([^:'(\s]+)", re.MULTILINE)
USAGE = """\
usage: take_release.sh <tag> [--remote <name>]

  1 fetch · git fetch <remote> --tags          (the remote defaults to `template`)
  2 census · divergence_census.sh --against <tag>
  3 merge · git merge --no-edit <tag>
  4 fold · manage.py fold_migrations <app>, each app the merge left two leaves in
  5 sdk · divergence_census.sh --against <tag> --sdk, from the release this checkout stood on
    base · scripts/local/template-base = the tag's commit, the base the gate's rule 60 reads
  6 gate · check.sh --fast
  Each step prints its line; a red one stops the road with its first line and `next:`.
  The tree must be clean (tracked files) before step 1; scripts/local/template-base is exempt

exit: 0 taken · 1 a step is red · 2 refused, or a step could not look.
"""


def git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=False)


def conflicted(root: Path) -> list[str]:
    """The paths the merge left unmerged."""
    return git(root, "diff", "--name-only", "--diff-filter=U").stdout.split()


def stopped(step: str, ran: Ran, tag: str, how: str = "") -> int:
    """A red step's line, its first red line located, and the `next:` that resumes the road."""
    word = "could not look" if ran.code == 2 else "red"
    out(f"{word}: {first_red(ran.text) or 'no red line located — the log has the whole answer'}")
    out(f"next: {how or f'fix what {step} names'}, then ./scripts/take_release.sh {tag}")
    return 2 if ran.code == 2 else 1


def say(n: int, step: Step, ran: Ran) -> None:
    out(f"{n}/6 {step.name} · {' '.join(step.argv)}")
    out(f"    exit {ran.code} ({ran.seconds}s) · log {ran.log}")


def road(root: Path, tag: str, remote: str, runner: Runner = run_step) -> int:
    """The six steps in order; the first red stops the road."""
    out(f"== take_release {tag} · {root}")
    fetch = Step("fetch", ("git", "fetch", remote, "--tags"))
    ran = runner(root, fetch, "take-release")
    say(1, fetch, ran)
    if ran.code:
        return stopped("the fetch", ran, tag, f"check the `{remote}` remote")
    if git(root, "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}").returncode:
        out(f"could not look: {tag} names no commit after the fetch")
        out(f"next: git ls-remote --tags {remote}, then ./scripts/take_release.sh <a tag it lists>")
        return 2
    stood_on = git(root, "merge-base", "HEAD", tag).stdout.strip()
    census = Step("census", (CENSUS, "--against", tag))
    ran = runner(root, census, "take-release")
    say(2, census, ran)
    newer = newer_locks(root, tag)
    if newer:
        names = "/".join(Path(lock).name for lock in newer)
        pins = sum(newer.values())
        out(f"    locks: the release's {names} are newer than this product's ({pins} pins)")
    if ran.code:
        return stopped("the census", ran, tag)
    merge = Step("merge", ("git", "merge", "--no-edit", tag))
    ran = runner(root, merge, "take-release")
    say(3, merge, ran)
    leaves = conflicted(root)
    if ran.code and not leaves:
        return stopped("the merge", ran, tag)
    other = [p for p in leaves if not p.endswith(MIGRATION_LEAF)]
    if other:
        out(f"red: {other[0]} — the merge left {len(other)} conflict(s) outside the migrations")
        for path in other[1:]:
            out(f"     {path}")
        out(f"next: resolve them, git commit, then ./scripts/take_release.sh {tag}")
        return 1
    apps = [p.split("/")[1] for p in leaves]
    if not apps:
        out("4/6 fold · no app's migrations were left with two leaves — nothing to fold")
    for n, app in enumerate(apps):
        fold = Step("fold", (python(root), "manage.py", "fold_migrations", app))
        ran = runner(root, fold, "take-release")
        say(4, fold, ran)
        if ran.code:
            return stopped("fold_migrations", ran, tag, f"read the log, fold apps/{app} by hand")
        if n == len(apps) - 1:
            for each in apps:
                git(root, "add", "--", f"apps/{each}/migrations")
            done = git(root, "commit", "--no-edit")
            if done.returncode:
                out(f"red: the merge commit refused — {done.stdout.strip()[-300:]}")
                out(f"next: commit the folded merge, then ./scripts/take_release.sh {tag}")
                return 1
    sdk = Step("sdk", (CENSUS, "--against", tag, "--sdk"))
    ran = _sdk(runner, root, sdk, stood_on)
    say(5, sdk, ran)
    for line in ran.text.splitlines():
        if line.startswith(("== ", "   surface", "imports ", "run makemigrations", "census: sdk")):
            out(f"    {line}")
    if ran.code and NO_SDK in ran.text:
        out(f"    the census {tag} carries has no --sdk step — a release before the SDK")
    elif ran.code:
        return stopped("the SDK step", ran, tag, "rewrite each import it names (`--sdk --fix`)")
    record_base(root, tag)
    gate = Step("gate", ("./scripts/check.sh", "--fast"))
    ran = runner(root, gate, "take-release")
    say(6, gate, ran)
    if ran.code:
        return stopped("the gate", ran, tag)
    out(f"taken: {tag}")
    out("next: ./scripts/feature.sh <app> --loop for each app you own, then the PR road")
    return 0


def pins(lock: str, text: str) -> set[tuple[str, str]]:
    """`(package, version)` per pin `text` holds, read as the lock named `lock` is written."""
    if lock.endswith("pnpm-lock.yaml"):
        packages = text.split("\npackages:", 1)[-1] if "\npackages:" in text else ""
        return set(_PNPM_PIN.findall(packages))
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set()
    return {
        (str(p.get("name")), str(p.get("version")))
        for p in doc.get("package", [])
        if isinstance(p, dict)
    }


def newer_locks(root: Path, tag: str) -> dict[str, int]:
    """Each lock whose pins at `tag` this checkout's HEAD lacks, with how many it lacks."""
    found: dict[str, int] = {}
    for lock in LOCKS:
        theirs = git(root, "show", f"{tag}:{lock}")
        if theirs.returncode:
            continue
        ours = git(root, "show", f"HEAD:{lock}")
        lacking = pins(lock, theirs.stdout) - pins(lock, ours.stdout if not ours.returncode else "")
        if lacking:
            found[lock] = len(lacking)
    return found


def record_base(root: Path, tag: str) -> None:
    """Write the tag's commit to the declared-base drawer and print the line written."""
    path = root / TEMPLATE_BASE_DRAWER
    sha = git(root, "rev-parse", f"{tag}^{{commit}}").stdout.strip()
    if path.is_file():
        was = "".join(path.read_text().split())
        line = f"{was} → {sha}" if was != sha else f"{sha} (kept)"
    else:
        out(f"    base · {TEMPLATE_BASE_DRAWER} was absent — this product never declared it")
        line = sha
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sha + "\n")
    out(f"    base · {TEMPLATE_BASE_DRAWER}: {line} ({tag}^{{commit}})")
    out(f"    base · commit it with the release: git add {TEMPLATE_BASE_DRAWER} && git commit")


def _sdk(runner: Runner, root: Path, step: Step, stood_on: str) -> Ran:
    """The SDK step read from the release this checkout stood on before the merge."""
    if not stood_on or os.environ.get("DJB_TEMPLATE_BASE"):
        return runner(root, step, "take-release")
    os.environ["DJB_TEMPLATE_BASE"] = stood_on
    try:
        return runner(root, step, "take-release")
    finally:
        del os.environ["DJB_TEMPLATE_BASE"]


def main(argv: Sequence[str] | None = None, root: Path = ROOT, runner: Runner = run_step) -> int:
    """`take_release.sh <tag>`: 0 taken · 1 a step is red · 2 refused or could not look."""
    words = list(sys.argv[1:] if argv is None else argv)
    if any(w in ("-h", "--help") for w in words):
        sys.stdout.write(USAGE)
        return 0
    if piped():
        err("!! take_release.sh refuses pipes — run it bare or redirect to a file.")
        return 2
    remote = "template"
    if "--remote" in words:
        at = words.index("--remote")
        if at + 1 >= len(words):
            err("!! --remote takes the remote's name")
            return 2
        remote = words.pop(at + 1)
        words.pop(at)
    if len(words) != 1 or words[0].startswith("-"):
        err(f"!! take_release.sh takes one release tag\n{USAGE}")
        return 2
    if remote not in git(root, "remote").stdout.split():
        err(f"!! no `{remote}` remote — `git remote add {remote} <the template's repository>`")
        return 2
    if git(
        root,
        "status",
        "--porcelain",
        "--untracked-files=no",
        "--",
        ".",
        f":!{TEMPLATE_BASE_DRAWER}",
    ).stdout.strip():
        err(
            "!! the tree has uncommitted changes — commit or stash them; a merge needs a clean tree"
        )
        return 2
    return road(root, words[0], remote, runner)


if __name__ == "__main__":
    raise SystemExit(main())
