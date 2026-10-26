"""The layer boundary (rule 95) driven through real commits in a scratch mirror of HEAD."""

# does-not-cover: the real pre-commit's `--fast` tail; the scratch pre-commit is the layer step.

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.scratch import require_scratch

pytestmark = pytest.mark.drives(
    "quality/djb/boundary.py",
    "quality/djb/cli.py",
    "scripts/githooks/",
    "quality/djb/rituals/divergence.py",
    "quality/djb/ledger.py",
    "quality/checks/rule_95.py",
)

ROOT = Path(__file__).resolve().parents[2]
SANCTION = "joe: the product needs one more dependency"
REFUSAL = (
    "quality/x.py is the platform's; it arrives by release fold (scripts/pm_fold.sh), never by a"
    " product commit — a divergence needs DJB_LAYER_SANCTION and its divergence: line (rule 60);"
    " a product's territory is its own apps, frontend/ and their derived files"
    " (docs/sdk/the-one-path.md)"
)


def git(where: Path, *argv: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        ["git", "-C", str(where), *argv], capture_output=True, text=True, env=env or clean_env()
    )
    if done.returncode != 0:
        raise CouldNotLook(f"git {' '.join(argv)} in {where}: {done.stderr.strip()}")
    return done.stdout.strip()


def clean_env(**extra: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and not k.startswith("DJB_LAYER_")
    }
    return {**env, **extra}


@dataclass(frozen=True)
class Ran:
    rc: int
    out: str


@dataclass
class Mirror:
    """A repository on HEAD's objects, its hooks a scratch pair, and the base it was built at."""

    path: Path
    base: str
    product_base: str = ""

    def reset(self) -> None:
        git(self.path, "reset", "-q", "--hard", self.base)
        git(self.path, "clean", "-qfd")

    def write(self, rel: str, text: str, append: bool = False) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a" if append else "w") as out:
            out.write(text)

    def around_the_hook(self, message: str, *paths: str) -> str:
        """Commit `paths` with the hook stepped around — the subject of the census; the new sha."""
        git(self.path, "add", "--", *paths)
        git(self.path, "commit", "-q", "--no-verify", "-m", message)
        return git(self.path, "rev-parse", "HEAD")

    def declare_namespace(self) -> None:
        """A product: the namespace declared in the drawer, committed past the hook."""
        self.reset()
        self.write("quality/local/rules.yaml", "rule_id_namespace: acme\n")
        self.product_base = self.around_the_hook(
            "acme: the product declares its namespace", "quality/local/rules.yaml"
        )

    def commit(self, label: str, sanction: str = "") -> Ran:
        """Stage everything the case wrote and commit it through the scratch hooks."""
        env = clean_env(DJB_LAYER_SANCTION=sanction)
        git(self.path, "add", "-A", env=env)
        done = subprocess.run(
            ["git", "-C", str(self.path), "commit", "-q", "-m", label],
            capture_output=True,
            text=True,
            env=env,
        )
        return Ran(done.returncode, done.stdout + done.stderr)

    def census(self, sanction: str = "") -> Ran:
        """The boundary census over the mirror's history since the product base."""
        self.write("scripts/local/template-base", f"{self.product_base}\n")
        done = subprocess.run(
            [".venv/bin/python", "-m", "quality.djb.boundary", "--census"],
            cwd=self.path,
            capture_output=True,
            text=True,
            env=clean_env(DJB_LAYER_SANCTION=sanction),
        )
        return Ran(done.returncode, done.stdout + done.stderr)


def build_mirror(dest: Path) -> Path:
    """A fresh repository at `dest` checked out at ROOT's HEAD, borrowing its object store."""
    common = Path(git(ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    git(dest.parent, "init", "-q", str(dest))
    (dest / ".git/objects/info/alternates").write_text(f"{common / 'objects'}\n")
    git(dest, "fetch", "-q", "--no-tags", str(ROOT), "HEAD")
    git(dest, "checkout", "-q", "-f", "--detach", "FETCH_HEAD")
    for key, value in (
        ("user.email", "layer@example.invalid"),
        ("user.name", "layer"),
        ("commit.gpgsign", "false"),
        ("gc.auto", "0"),
    ):
        git(dest, "config", key, value)
    for rel in git(ROOT, "diff", "--name-only", "--diff-filter=D", "HEAD").splitlines():
        (dest / rel).unlink(missing_ok=True)
    changed = git(ROOT, "diff", "--name-only", "--diff-filter=d", "HEAD").splitlines()
    for rel in changed + git(ROOT, "ls-files", "--others", "--exclude-standard").splitlines():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest / rel)
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "--no-verify", "--allow-empty", "-m", "the checkout as it stands")
    if (ROOT / ".env").is_file():
        shutil.copy(ROOT / ".env", dest / ".env")
    (dest / ".venv").mkdir()
    for part in ("bin", "lib"):
        (dest / ".venv" / part).symlink_to(ROOT / ".venv" / part)
    shutil.copy(ROOT / ".venv/pyvenv.cfg", dest / ".venv/pyvenv.cfg")
    return dest


def scratch_hooks(home: Path) -> Path:
    """The real pre-commit's layer line alone, and the real commit-msg whole."""
    layer = [
        line
        for line in (ROOT / "scripts/githooks/pre-commit").read_text().splitlines()
        if "quality.djb.cli hook pre-commit" in line
    ]
    if not layer:
        raise CouldNotLook("scripts/githooks/pre-commit carries no layer step to run")
    home.mkdir()
    (home / "pre-commit").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'cd "$(git rev-parse --show-toplevel)"\nhook_index="${GIT_INDEX_FILE:-}"\n'
        f"{layer[0]}\n"
    )
    shutil.copy(ROOT / "scripts/githooks/commit-msg", home / "commit-msg")
    for hook in ("pre-commit", "commit-msg"):
        (home / hook).chmod(0o755)
    return home


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Mirror]:
    """One mirror per worker, its hooks the scratch pair."""
    home = require_scratch(tmp_path_factory.mktemp("layer"), ROOT)
    path = build_mirror(home / "mirror")
    git(path, "config", "core.hooksPath", str(scratch_hooks(home / "hooks")))
    yield Mirror(path, git(path, "rev-parse", "HEAD"))
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def mirror(built: Mirror) -> Mirror:
    built.reset()
    built.product_base = ""
    return built


def test_the_layer_step_runs_before_the_docs_only_admission() -> None:
    pre = (ROOT / "scripts/githooks/pre-commit").read_text()
    layer = pre.find("quality.djb.cli hook pre-commit")
    admission = pre.find('gate_docs_only_admits "$p"')
    assert layer != -1 and admission != -1 and layer < admission, (layer, admission)
    assert "quality.djb.cli hook commit-msg" in (ROOT / "scripts/githooks/commit-msg").read_text()


def test_the_template_tree_freezes_nothing(mirror: Mirror) -> None:
    mirror.write("quality/x.py", "x = 1\n")
    ran = mirror.commit("template-tree")
    assert ran.rc == 0, ran.out
    assert "layer: template tree — nothing frozen" in ran.out


def test_a_platform_path_is_refused_with_the_sentence(mirror: Mirror) -> None:
    mirror.declare_namespace()
    mirror.write("quality/x.py", "x = 1\n")
    ran = mirror.commit("platform-path")
    assert ran.rc == 1, ran.out
    assert REFUSAL in ran.out
    assert git(mirror.path, "rev-parse", "HEAD") == mirror.product_base, "HEAD moved"


def test_a_platform_path_in_a_product_namespace_is_refused(mirror: Mirror) -> None:
    """A staged platform module a scaffold does not own: refused, the territory's page named."""
    mirror.declare_namespace()
    mirror.write("apps/core/service.py", "# acme: an edit\n", append=True)
    ran = mirror.commit("platform-module")
    assert ran.rc == 1, ran.out
    assert REFUSAL.replace("quality/x.py", "apps/core/service.py") in ran.out, ran.out
    assert git(mirror.path, "rev-parse", "HEAD") == mirror.product_base, "HEAD moved"


def test_a_product_commit_to_the_core_family_census_is_refused_naming_the_page(
    mirror: Mirror,
) -> None:
    """A product's families go to its drawer; the core census is the platform's."""
    mirror.declare_namespace()
    mirror.write("apps/core/api/frozen_families.py", "# acme: a family\n", append=True)
    ran = mirror.commit("core-families")
    assert ran.rc == 1, ran.out
    assert REFUSAL.replace("quality/x.py", "apps/core/api/frozen_families.py") in ran.out, ran.out
    assert git(mirror.path, "rev-parse", "HEAD") == mirror.product_base, "HEAD moved"


def test_the_empty_tree_is_gits_own(tmp_path: Path) -> None:
    """Before a repository's first commit the staged set diffs against git's empty tree."""
    from quality.djb import boundary

    said = subprocess.run(
        ["git", "hash-object", "-t", "tree", "/dev/null"], capture_output=True, text=True
    )
    assert boundary.EMPTY_TREE == said.stdout.strip(), said
    fresh = require_scratch(tmp_path / "fresh", ROOT)
    git(tmp_path, "init", "-q", str(fresh))
    (fresh / "a.txt").write_text("a\n")
    git(fresh, "add", "a.txt")
    assert boundary.head(fresh) == boundary.EMPTY_TREE
    assert boundary.staged(fresh) == ["a.txt"]


def test_a_stack_path_needs_the_sanction_and_carries_it_as_a_trailer(mirror: Mirror) -> None:
    mirror.declare_namespace()
    mirror.write("pyproject.toml", "# acme: a dependency\n", append=True)
    ran = mirror.commit("stack-unsanctioned")
    assert ran.rc == 1 and "pyproject.toml is the stack's" in ran.out, ran.out
    ran = mirror.commit("stack-sanctioned", SANCTION)
    assert ran.rc == 0 and "layer: sanctioned by joe" in ran.out, ran.out
    trailer = git(mirror.path, "log", "-1", "--format=%(trailers:key=Layer-Sanction)")
    assert trailer.strip() == f"Layer-Sanction: {SANCTION}"


def test_a_product_path_is_admitted_silently(mirror: Mirror) -> None:
    mirror.declare_namespace()
    mirror.write("apps/acme/models.py", "X = 1\n")
    mirror.write("frontend/src/x.ts", "export const x = 1\n")
    ran = mirror.commit("product-path")
    assert ran.rc == 0, ran.out
    assert "is the platform's" not in ran.out and "is the stack's" not in ran.out, ran.out


def test_removing_the_namespace_is_refused(mirror: Mirror) -> None:
    mirror.declare_namespace()
    mirror.write("quality/local/rules.yaml", "{}\n")
    ran = mirror.commit("namespace-removed")
    assert ran.rc == 1 and "removes rule_id_namespace" in ran.out, ran.out


def test_a_commit_that_stepped_around_the_hook_is_named_by_the_census(mirror: Mirror) -> None:
    mirror.declare_namespace()
    mirror.write("quality/x.py", "x = 1\n")
    sha = mirror.around_the_hook("acme: an edit around the hook", "quality/x.py")
    ran = mirror.census()
    assert ran.rc == 1, ran.out
    assert f"unsanctioned: {sha} · quality/x.py" in ran.out


def test_a_sanctioned_or_fold_commit_is_silent_in_the_census(mirror: Mirror) -> None:
    mirror.declare_namespace()
    mirror.write("pyproject.toml", "# acme: a dependency\n", append=True)
    assert mirror.commit("census-sanctioned", SANCTION).rc == 0
    mirror.write("quality/y.py", "y = 1\n")
    mirror.around_the_hook("fold: 1 declared path(s) regenerated", "quality/y.py")
    ran = mirror.census()
    assert ran.rc == 0, ran.out
    assert "census: commits=2 unsanctioned=0 pending=0" in ran.out


def test_the_interpreter_pin_is_the_platforms(mirror: Mirror) -> None:
    mirror.declare_namespace()
    mirror.write(".python-version", "3.13\n")
    ran = mirror.commit("interpreter-pin")
    assert ran.rc == 1, ran.out
    assert ".python-version is the platform's; it arrives by release fold" in ran.out


def test_a_compose_override_is_the_stacks(mirror: Mirror) -> None:
    mirror.declare_namespace()
    mirror.write("compose.override.yaml", "services: {}\n")
    ran = mirror.commit("compose-override")
    assert ran.rc == 1 and "compose.override.yaml is the stack's" in ran.out, ran.out


def test_a_pending_stack_edit_is_red_whatever_the_environment(mirror: Mirror) -> None:
    mirror.declare_namespace()
    mirror.write("pyproject.toml", "# acme: a dependency\n", append=True)
    ran = mirror.census(SANCTION)
    assert ran.rc == 1 and "pending: pyproject.toml" in ran.out, ran.out
