"""`python -m quality.djb.rituals.divergence` driven over throwaway product checkouts it builds."""

# deleted: case_roads_mirror_agrees_with_the_census — the mirror is gone; the census is the one reader on both sides  # noqa: E501
# pin: test_a_product_road_for_a_job_the_release_marks_is_a_collision (quality.roads.census)
# does-not-cover: a real template release — every base and release here is a fixture tag.
# does-not-cover: the road census's own grammar — `apps/core/tests/test_road_census.py` owns it.

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.djb.rituals import divergence
from quality.tests.fixtures.capture import Captured, run_to

pytestmark = pytest.mark.drives(
    "quality/djb/rituals/divergence.py",
    "quality/roads.py",
    "quality/partition.yaml",
    "scripts/archaeology_lib.sh",
    "scripts/gate_refuse.sh",
    "scripts/divergence_census.sh",
)

ROOT = Path(__file__).resolve().parents[2]
ENTRY = (
    "import sys; from pathlib import Path; "
    "from quality.djb.rituals.divergence import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
#: A death planted after the guard is armed and before any end the census authors.
DYING_ENTRY = (
    "import sys; from pathlib import Path; "
    "import quality.djb.rituals.divergence as d; "
    "d.platform_apps = lambda root: A_VARIABLE_NOTHING_EVER_SETS; "
    "sys.exit(d.main(sys.argv[1:], root=Path.cwd()))"
)
PLACE = "where the tag is fetched (a laptop with the 'template' remote), then commit the drawer"


@dataclass
class World:
    """One throwaway product checkout and the directory its captures go to."""

    repo: Path
    sink: Path

    def git(self, *argv: str) -> str:
        """`git -C <repo> <argv>`'s stdout; a failure fails the test."""
        done = subprocess.run(
            ["git", "-C", str(self.repo), *argv], capture_output=True, text=True, check=False
        )
        assert done.returncode == 0, f"git {' '.join(argv)}: {done.stderr}"
        return done.stdout.strip()

    def write(self, rel: str, text: str) -> None:
        """Write one file, its directories made."""
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def append(self, rel: str, text: str) -> None:
        """Append to one file."""
        with (self.repo / rel).open("a") as sink:
            sink.write(text)

    def commit(self, message: str, *paths: str) -> None:
        """Stage `paths` (every change when none) and commit."""
        self.git("add", *(paths or ("-A",)))
        self.git("commit", "-q", "-m", message)

    def tag(self, name: str) -> None:
        """An annotated tag at HEAD, moved if it exists."""
        self.git("tag", "-f", "-a", name, "-m", name, "HEAD")

    def env(self, base: str | None, **extra: str) -> dict[str, str]:
        """The census's environment: this checkout's package importable, the base typed or not."""
        env = {k: v for k, v in os.environ.items() if k != "DJB_TEMPLATE_BASE"}
        env["PYTHONPATH"] = str(ROOT)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if base is not None:
            env["DJB_TEMPLATE_BASE"] = base
        return {**env, **extra}

    def census(self, *args: str, base: str | None = None, entry: str = ENTRY) -> Captured:
        """One census of the checkout, both streams to a file outside it."""
        sink = self.sink / f"census-{len(list(self.sink.glob('census-*')))}.out"
        return run_to(sink, [sys.executable, "-c", entry, *args], self.repo, self.env(base))

    def against(self, *args: str) -> Captured:
        """`run_against`: the fixture's own base typed, so the exit is the collision half's."""
        return self.census(*args, base="v0.1.0")


def census_count(text: str, field: str) -> str:
    """`<field>=<n>` off the `census:` line."""
    for line in text.splitlines():
        if line.startswith("census:"):
            for word in line.split():
                if word.startswith(f"{field}="):
                    return word.split("=", 1)[1]
    return ""


def build_repo(path: Path, sink: Path) -> World:
    """A PRODUCT at v0.1.0: one tracked file per ownership class and the classifier it sources."""
    w = World(path, sink)
    for rel, text in (
        (
            "quality/partition.yaml",
            "schema: v1\n\nplatform_apps:\n  - core\n\nclosure_classes: []\n",
        ),
        ("TEMPLATE_VERSION", "0.1.0\n"),
        (
            "docs/product/architecture.md",
            "# architecture — the product's own decisions\n\n**Status: standing.**\n",
        ),
        ("scripts/check.sh", "# the gate\n"),
        ("scripts/x.sh", "# a template-owned script\n"),
        ("config/settings.py", "# settings\n"),
        ("apps/core/services.py", "# the platform app\n"),
        ("apps/core/roles.py", "ROLES = {}\n"),
        ("apps/core/api/frozen_families.py", "FAMILIES = {}\n"),
        ("apps/zzz_product_app/models.py", "# the product's own app\n"),
        ("docs/product/queue.md", "# queue — the product's ledger\n"),
        ("docs/product/build-contract.md", "# the build contract\n"),
        ("docs/product/design/patterns.md", "# the pattern book\n"),
        ("pyproject.toml", "[project]\n"),
        (".github/workflows/ci.yml", "name: ci\n"),
        (".github/workflows/nightly-proof.yml", "name: nightly-proof\n"),
    ):
        w.write(rel, text)
    for rel in ("scripts/archaeology_lib.sh", "scripts/gate_refuse.sh"):
        shutil.copy(ROOT / rel, path / rel)
    (path / "deploy").mkdir()
    for step in (
        ["init", "-q"],
        ["symbolic-ref", "HEAD", "refs/heads/main"],
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "t"],
        ["config", "commit.gpgsign", "false"],
        ["config", "tag.gpgsign", "false"],
    ):
        w.git(*step)
    w.commit("the template at v0.1.0")
    w.tag("v0.1.0")
    return w


@pytest.fixture
def product(scratch: Path) -> Iterator[Callable[[str], World]]:
    """`product(name)` builds one fixture product under `scratch`."""
    (scratch / "out").mkdir()
    yield lambda name: build_repo(scratch / name, scratch / "out")


@pytest.fixture
def repo(product: Callable[[str], World]) -> World:
    """The shared fixture product the drive's linear half runs over."""
    return product("product")


def base_of(w: World) -> str:
    """The fixture's base commit."""
    return w.git("rev-parse", "v0.1.0^{commit}")


# --- the base: three readers, and no default -----------------------------------------------------


def test_no_base_declared_is_exit_2(repo: World) -> None:
    said = repo.census()
    assert said.rc == 2
    assert "NO BASE IS DECLARED" in said.text()


def test_if_declared_with_no_base_is_a_printed_skip(repo: World) -> None:
    said = repo.census("--if-declared")
    assert said.rc == 0
    assert "SKIPPED" in said.text()
    assert "census: owned=" in said.text()


def test_an_unknown_flag_is_exit_2(repo: World) -> None:
    said = repo.census("--nonsense")
    assert said.rc == 2
    assert "unknown argument '--nonsense'" in said.text()


def test_a_piped_stdout_is_refused(repo: World) -> None:
    done = subprocess.run(
        [sys.executable, "-c", ENTRY],
        cwd=repo.repo,
        env=repo.env(base_of(repo)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert "refuses pipes" in done.stderr


def test_the_declared_base_is_read_from_the_product_drawer(repo: World) -> None:
    base = base_of(repo)
    repo.write(divergence.TEMPLATE_BASE_DRAWER, f"{base}\n")
    said = repo.census()
    assert said.rc == 0, said.text()
    assert f"   base       {base}  (from scripts/local/template-base)" in said.text()
    repo.write(divergence.TEMPLATE_BASE_DRAWER, "")
    said = repo.census()
    assert said.rc == 2
    assert "is empty" in said.text()


def test_the_drawer_count_is_the_list_and_not_the_filesystem(repo: World) -> None:
    base = base_of(repo)
    bare = census_count(repo.census(base=base).text(), "drawers")
    repo.write("quality/local/rules.yaml", "rule_id_namespace: acme\n")
    repo.write("quality/local/canary/x-1/plan.md", "rule: x-1 — a drawer rule fixture\n")
    repo.write("scripts/local/legs/a.sh", "# a product leg\n")
    said = repo.census(base=base)
    assert said.rc == 0, said.text()
    assert census_count(said.text(), "drawers") == bare == "3"
    assert "reserved paths are the product" in said.text()
    assert "(**/local/** *.local.md apps/conftest_local.py)" in said.text()


def test_the_classifier_is_a_python_body_and_runs_no_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`rules_for` answers in-process; a classifier that shells out is the deviation it replaced."""

    def no_shell(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"rules_for ran a process: {args!r}")

    monkeypatch.setattr(subprocess, "run", no_shell)
    found = divergence.rules_for(
        ["scripts/check.sh", "scripts/test_impact.json", "apps/x/models.py", "nowhere/at/all"]
    )
    assert found == {
        "scripts/check.sh": ["R3"],
        "scripts/test_impact.json": ["R12"],
        "apps/x/models.py": ["R1"],
        "nowhere/at/all": [],
    }


#: The shell classifier, batched: one `rules_for` per path read on stdin.
SHELL_RULES_FOR = """
. scripts/archaeology_lib.sh || exit 3
while IFS= read -r p; do
    rules_for "$p" >/dev/null
    printf '%s\\t%s\\n' "$p" "$RULES_FOR"
done
"""


def test_the_python_classifier_equals_the_shell_one_over_every_tracked_path() -> None:
    """`archaeology_lib.sh::rules_for` stays for the archaeology leg; the two never disagree."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    probes = [
        *tracked,
        "docs/product/cycles/README.md",
        "/".join(("docs/product/reports", "x.md")),
        "nowhere",
    ]
    done = subprocess.run(
        ["bash", "-c", SHELL_RULES_FOR],
        cwd=ROOT,
        input="".join(f"{p}\n" for p in probes),
        capture_output=True,
        text=True,
        check=True,
    )
    shell = {}
    for line in done.stdout.splitlines():
        path, _, ids = line.partition("\t")
        shell[path] = ids.split()
    assert len(shell) == len(set(probes))
    assert divergence.rules_for(probes) == shell


def test_a_death_part_way_is_exit_2_on_every_bash(repo: World) -> None:
    said = repo.census(entry=DYING_ENTRY)
    assert said.rc == 2
    assert "DIED part-way" in said.text()
    assert "NameError" in said.text()


# --- the divergence half: what is, and what is not, a divergence ---------------------------------


def test_a_product_that_changed_nothing_is_clean(repo: World) -> None:
    said = repo.census(base=base_of(repo))
    assert said.rc == 0, said.text()
    assert "\n== CLEAN" in said.text()


def test_the_owned_set_is_derived_and_a_new_owned_path_joins_it(repo: World) -> None:
    base = base_of(repo)
    before = int(census_count(repo.census(base=base).text(), "owned"))
    repo.write("deploy/provision_extra.sh", "# a product stage step\n")
    repo.commit("a new R3 path")
    said = repo.census(base=base)
    assert said.rc == 1, said.text()
    assert "divergence: deploy/provision_extra.sh" in said.text()
    assert int(census_count(said.text(), "owned")) == before + 1


def test_an_edit_in_a_template_owned_script_names_the_path_the_commit_and_the_line(
    repo: World,
) -> None:
    base = base_of(repo)
    repo.append("scripts/x.sh", "# our own leg, re-applied every release\n")
    repo.commit("our edit")
    sha = repo.git("rev-parse", "--short", "HEAD")
    said = repo.census(base=base)
    assert said.rc == 1, said.text()
    assert "divergence: scripts/x.sh" in said.text()
    assert sha in said.text()
    assert "divergence: scripts/x.sh — " in said.text()
    repo.append(
        "docs/product/architecture.md",
        "\ndivergence: `scripts/x.sh` — our stage leg, until the template grows the drawer.\n",
    )
    repo.commit("name the divergence")
    said = repo.census(base=base)
    assert said.rc == 0, said.text()
    assert "named-divergence: scripts/x.sh" in said.text()


@pytest.mark.parametrize(
    ("path", "how"),
    [
        ("scripts/local/legs/x.sh", "create"),
        ("apps/zzz_product_app/models.py", "append"),
        ("apps/core/roles.py", "append"),
        ("pyproject.toml", "append"),
        ("docs/product/queue.md", "append"),
        (".github/workflows/zzz_product.yml", "create"),
        (".github/workflows/nightly-proof.yml", "append"),
        ("docs/product/design/patterns.local.md", "create"),
    ],
)
def test_the_silent_half_is_the_products(repo: World, path: str, how: str) -> None:
    if how == "append":
        repo.append(path, "# the product changed this\n")
    else:
        repo.write(path, "# the product wrote this\n")
    repo.commit(f"product change: {path}")
    said = repo.census(base=base_of(repo))
    assert said.rc == 0, said.text()
    assert f"divergence: {path}" not in said.text()


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "docs/product/design/patterns.md",
        "apps/core/services.py",
    ],
)
def test_a_template_owned_file_edited_is_a_divergence(repo: World, path: str) -> None:
    repo.append(path, "# our tweak\n")
    repo.commit(f"edit {path}")
    said = repo.census(base=base_of(repo))
    assert said.rc == 1, said.text()
    assert f"divergence: {path}" in said.text()


def test_a_second_design_file_is_the_templates(repo: World) -> None:
    owned = int(census_count(repo.census(base=base_of(repo)).text(), "owned"))
    second = "/".join(("docs/product/design", "zzz_notes.md"))
    repo.write(second, "# a second design file the template ships\n")
    repo.commit("the template grows a second design file")
    grown = repo.git("rev-parse", "HEAD")
    said = repo.census(base=grown)
    assert int(census_count(said.text(), "owned")) == owned + 1
    repo.append(second, "# our edit to it\n")
    repo.commit("edit the second design file")
    said = repo.census(base=grown)
    assert said.rc == 1, said.text()
    assert f"divergence: {second}" in said.text()


def test_an_untracked_owned_file_is_a_divergence_git_diff_cannot_see(repo: World) -> None:
    repo.write("scripts/not_yet_committed.sh", "# not committed yet\n")
    said = repo.census(base=base_of(repo))
    assert said.rc == 1, said.text()
    assert "divergence: scripts/not_yet_committed.sh" in said.text()
    assert "a file the base does not have" in said.text()


def test_a_declared_base_that_does_not_resolve_is_exit_2(repo: World) -> None:
    said = repo.census(base="v9.9.9")
    assert said.rc == 2
    assert "does not resolve" in said.text()


def test_a_platform_app_edit_is_seen_against_the_real_partition_list(repo: World) -> None:
    shutil.copy(ROOT / "quality/partition.yaml", repo.repo / "quality/partition.yaml")
    repo.commit("the template at v0.1.0, with its real platform-app list", "quality/partition.yaml")
    repo.tag("v0.1.0")
    names = divergence.platform_apps(repo.repo)
    last = names[-1] if names else ""
    assert last and last != "core", (
        f"the real list reads no last name distinct from core ({last!r})"
    )
    repo.append("apps/core/services.py", "# our patch to the platform app\n")
    repo.commit("edit a platform app")
    said = repo.census(base="v0.1.0")
    assert said.rc == 1, said.text()
    assert "\n   divergence: apps/core/services.py" in said.text()
    assert census_count(said.text(), "diverged") == "1"
    assert census_count(said.text(), "unnamed") == "1"
    repo.append("docs/product/architecture.md", "\ndivergence: apps/core/services.py — probe\n")
    repo.commit("name the divergence")
    said = repo.census(base="v0.1.0")
    assert said.rc == 0, said.text()
    assert "named-divergence: apps/core/services.py" in said.text()
    repo.write(f"apps/{last}/zzz_probe.py", "# a probe under the last platform app\n")
    repo.commit("edit the last platform app")
    said = repo.census(base="v0.1.0")
    assert said.rc == 1, said.text()
    assert f"\n   divergence: apps/{last}/zzz_probe.py" in said.text()
    repo.git("rm", "-q", f"apps/{last}/zzz_probe.py")
    repo.commit("undo")
    repo.append("apps/zzz_product_app/models.py", "# the product changed this\n")
    repo.commit("product change")
    said = repo.census(base="v0.1.0")
    assert said.rc == 0, said.text()
    assert "divergence: apps/zzz_product_app/models.py" not in said.text()


def test_a_drawer_naming_an_unfetched_tag_is_answered_with_the_tags_commit(repo: World) -> None:
    drawer = divergence.TEMPLATE_BASE_DRAWER
    repo.write(drawer, "v0.0.0-unfetched\n")
    said = repo.census()
    text = said.text()
    assert said.rc == 2, text
    assert (
        "the declared base does not resolve to a commit in this checkout: v0.0.0-unfetched" in text
    )
    assert f"   or write the tag's commit in the drawer, {PLACE}:" in text
    assert f"     git rev-parse 'v0.0.0-unfetched^{{commit}}' > {drawer}" in text
    (repo.repo / drawer).unlink()
    said = repo.census()
    text = said.text()
    assert said.rc == 2, text
    assert f"echo <commit-or-tag> > {drawer}" in text
    assert "a product's CI resolves a commit and not the template's tag" in text
    assert f"the tag's commit, {PLACE}:" in text
    tag_object = repo.git("rev-parse", "refs/tags/v0.1.0")
    repo.git("remote", "add", "template", str(repo.sink / "template-not-fetched.git"))
    repo.git("tag", "-d", "v0.1.0")
    said = repo.census()
    text = said.text()
    assert said.rc == 2, text
    assert "(from the 'template' remote, derived from TEMPLATE_VERSION)" in text
    assert "the declared base does not resolve to a commit in this checkout: v0.1.0" in text
    assert f"     git rev-parse 'v0.1.0^{{commit}}' > {drawer}" in text
    repo.git("update-ref", "refs/tags/v0.1.0", tag_object)
    repo.git("remote", "remove", "template")
    commit = repo.git("rev-parse", "v0.1.0^{commit}")
    verdict = repo.census(base="v0.1.0").rc
    assert verdict != 2
    repo.write(drawer, f"{commit}\n")
    said = repo.census()
    assert said.rc == verdict
    assert f"   base       {commit}  (from {drawer})" in said.text()
    repo.write(drawer, "v0.1.0\n")
    said = repo.census()
    assert said.rc == verdict
    assert f"   base       v0.1.0  (from {drawer})" in said.text()


def test_with_a_template_remote_the_base_is_derived_from_template_version(
    repo: World,
) -> None:
    upstream = repo.sink / "upstream"
    subprocess.run(["git", "clone", "-q", str(repo.repo), str(upstream)], check=True)
    repo.git("remote", "add", "template", str(upstream))
    said = repo.census()
    assert said.rc == 0, said.text()
    assert "v0.1.0" in said.text()
    assert "template' remote" in said.text()
    assert "$(" not in said.text()
    repo.write("TEMPLATE_VERSION", "not-a-version\n")
    said = repo.census()
    assert said.rc == 2
    assert "TEMPLATE_VERSION does not read" in said.text()


def test_the_census_writes_nothing(repo: World) -> None:
    repo.append("scripts/x.sh", "# a divergence to make it do work\n")

    def state() -> str:
        return "\n".join(
            (repo.git("status", "--porcelain"), repo.git("rev-parse", "HEAD"), repo.git("tag"))
        )

    before = state()
    said = repo.census(base=base_of(repo))
    assert said.rc == 1, said.text()
    assert state() == before


# --- the collision census: a release's app against the product's own ----------------------------

REMEDY = divergence.COLL_REMEDY
KIND_REMEDY = (
    'remedy: give YOUR model a kind of its own — one line on its class, authz_kind = "<its own'
    ' word>"'
)
MOUNT_REMEDY = 'remedy: mount YOURS elsewhere — PREFIX = "<its own word>" in your api.py'
TAG_REMEDY = (
    'remedy: tag YOURS with a word of its own — Router(tags=["<its own word>"]) and the matching'
    " TAGS key"
)
TITLE_REMEDY = (
    'remedy: give YOUR tag a display of its own — Tag("<its own words>", …); a heading is what a'
    " reader of the document sees, and two apps under one heading are one section describing either"
)
SCHEMA_REMEDY = (
    "remedy: rename YOUR schema class — class <YourWord>Out(Schema); the document publishes one"
    " component per name and describes both apps' routes by whichever was discovered last"
)


def plant_app(w: World, app: str) -> None:
    """An apps.py whose label is its directory."""
    w.write(
        f"apps/{app}/apps.py",
        "from django.apps import AppConfig\n\n\nclass ZzzConfig(AppConfig):\n"
        f'    name = "apps.{app}"\n',
    )


def plant_initial(
    w: World, app: str, model: str, index: str, unique: str = "", table: str = ""
) -> None:
    """A first migration in `makemigrations`' shape: model, fields, index, constraints."""
    w.write(f"apps/{app}/migrations/__init__.py", "")
    lines = [
        "from django.db import migrations, models",
        "",
        "",
        "class Migration(migrations.Migration):",
        "    initial = True",
        "",
        "    dependencies = []",
        "",
        "    operations = [",
        "        migrations.CreateModel(",
        f'            name="{model}",',
        "            fields=[",
        '                ("id", models.BigAutoField(primary_key=True)),',
        '                ("name", models.CharField(max_length=10)),',
        "                (",
        '                    "owner",',
        "                    models.ForeignKey(",
        "                        on_delete=models.PROTECT,",
        '                        related_name="%(app_label)s_%(class)s_set",',
        '                        to="core.membership",',
        "                    ),",
        "                ),",
        "            ],",
        "            options={",
        '                "verbose_name": "zzz",',
        *([f'                "db_table": "{table}",'] if table else []),
        '                "indexes": [',
        f'                    models.Index(fields=["id"], name="{index}"),',
        "                ],",
        '                "constraints": [',
        *(
            [f'                    models.UniqueConstraint(fields=("name",), name="{unique}"),']
            if unique
            else []
        ),
        "                    models.CheckConstraint(",
        '                        condition=models.Q(("name", ""), _negated=True),',
        '                        name="zzz_check_shared_by_every_plant",',
        "                    ),",
        "                ],",
        "            },",
        "        ),",
        "    ]",
    ]
    w.write(f"apps/{app}/migrations/0001_initial.py", "\n".join(lines) + "\n")


def on_release(w: World, message: str, plant: Callable[[], None]) -> None:
    """`plant` committed on the release branch, v0.2.0 moved to it, main checked out again."""
    w.git("checkout", "-q", "zzz_release")
    plant()
    w.commit(message)
    w.tag("v0.2.0")
    w.git("checkout", "-q", "main")


def build_collision_world(w: World) -> World:
    """A product at v0.1.0 whose platform app has a schema; a release v0.2.0 adding an app."""
    plant_app(w, "core")
    w.write("apps/core/migrations/__init__.py", "")
    w.write(
        "apps/core/migrations/0001_initial.py",
        "from django.db import migrations, models\n\n\nclass Migration(migrations.Migration):\n"
        "    initial = True\n\n    dependencies = []\n\n    operations = [\n"
        '        migrations.CreateModel(\n            name="Membership",\n'
        '            fields=[("id", models.BigAutoField(primary_key=True))],\n        ),\n    ]\n',
    )
    w.write(
        "apps/core/migrations/0002_membership_recency.py",
        "from django.db import migrations, models\n\n\nclass Migration(migrations.Migration):\n"
        '    dependencies = [("core", "0001_initial")]\n\n    operations = [\n'
        '        migrations.AddIndex(\n            model_name="membership",\n'
        '            index=models.Index(fields=["id"], name="membership_recency"),\n'
        "        ),\n    ]\n",
    )
    w.commit("the template at v0.1.0, with a platform app's schema")
    w.tag("v0.1.0")
    w.git("checkout", "-q", "-b", "zzz_release")
    plant_app(w, "zzz_notes")
    plant_initial(w, "zzz_notes", "Note", "note_recency", "note_zzz_unique")
    w.commit("the release adds a platform app")
    w.tag("v0.2.0")
    w.git("checkout", "-q", "main")
    assert not (w.repo / "apps/zzz_notes").exists()
    plant_app(w, "zzz_product_app")
    plant_initial(w, "zzz_product_app", "Ledger", "ledger_recency")
    w.commit("the product's own app makes its first migration")
    return w


@pytest.fixture
def collision(product: Callable[[str], World]) -> World:
    """The collision world, main checked out."""
    return build_collision_world(product("collide"))


def collision_lines(text: str) -> list[str]:
    """Every `collision: ` line."""
    return [line for line in text.splitlines() if line.startswith("collision: ")]


def test_a_release_app_sharing_your_label_table_index_and_constraint_is_exit_2_per_pair(
    collision: World,
) -> None:
    plant_app(collision, "zzz_notes")
    plant_initial(collision, "zzz_notes", "Note", "note_recency")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    mig = "apps/zzz_notes/migrations/0001_initial.py"
    assert said.rc == 2, text
    assert "collision: label zzz_notes — apps/zzz_notes (yours) vs apps/zzz_notes (v0.2.0)" in text
    assert f"collision: table zzz_notes_note — yours ({mig}) vs v0.2.0 ({mig})" in text
    assert f"collision: index note_recency — yours ({mig}) vs v0.2.0 ({mig})" in text
    assert (
        "collision: kind note — yours (apps/zzz_notes · Note) vs v0.2.0 (apps/zzz_notes · Note)"
        in text
    )
    assert "collisions: labels=1 tables=1 indexes=1 constraints=0 kinds=1" in text
    assert len(collision_lines(text)) == 4
    assert text.count(REMEDY) == 3
    assert text.count(KIND_REMEDY) == 1
    plant_initial(collision, "zzz_notes", "Note", "note_recency", "note_zzz_unique")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert f"collision: constraint note_zzz_unique — yours ({mig}) vs v0.2.0 ({mig})" in text
    assert "collisions: labels=1 tables=1 indexes=1 constraints=1 kinds=1" in text
    assert len(collision_lines(text)) == 5
    assert "zzz_check_shared_by_every_plant" not in text


def test_distinct_labels_and_model_names_are_no_collision(collision: World) -> None:
    plant_app(collision, "zzz_orders")
    plant_initial(collision, "zzz_orders", "Order", "order_recency", "order_zzz_unique")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 0, text
    assert "collisions: none against v0.2.0" in text
    assert "collisions: labels=0 tables=0 indexes=0 constraints=0" in text
    assert not collision_lines(text)
    assert "\n== CLEAN" in text
    assert "release v0.2.0 parsed=2 unparsed=0 · yours parsed=2 unparsed=0" in text


def test_a_db_table_spelled_onto_a_release_table_is_a_table_pair(collision: World) -> None:
    plant_app(collision, "zzz_other")
    plant_initial(collision, "zzz_other", "Other", "other_recency", "", "zzz_notes_note")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: table zzz_notes_note — yours (apps/zzz_other/migrations/0001_initial.py)"
        " vs v0.2.0 (apps/zzz_notes/migrations/0001_initial.py)" in text
    )
    assert "collisions: labels=0 tables=1 indexes=0 constraints=0" in text
    assert len(collision_lines(text)) == 1


def test_an_inherited_index_name_collides_with_the_release_platform_app(collision: World) -> None:
    plant_app(collision, "zzz_people")
    plant_initial(collision, "zzz_people", "Membership", "membership_recency")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: index membership_recency — yours (apps/zzz_people/migrations/0001_initial.py)"
        " vs v0.2.0 (apps/core/migrations/0002_membership_recency.py)" in text
    )
    assert (
        "collision: kind membership — yours (apps/zzz_people · Membership) vs v0.2.0"
        " (apps/core · Membership)" in text
    )
    assert "collisions: labels=0 tables=0 indexes=1 constraints=0 kinds=1" in text
    assert len(collision_lines(text)) == 2


def test_an_index_subclass_name_is_in_the_population(collision: World) -> None:
    def release() -> None:
        collision.write(
            "apps/zzz_notes/migrations/0002_note_name_gin.py",
            "import django.contrib.postgres.indexes\nfrom django.db import migrations\n\n\n"
            "class Migration(migrations.Migration):\n"
            '    dependencies = [("zzz_notes", "0001_initial")]\n\n    operations = [\n'
            '        migrations.AddIndex(\n            model_name="note",\n'
            "            index=django.contrib.postgres.indexes.GinIndex(\n"
            '                fields=["name"], name="note_name_gin_zzz"\n            ),\n'
            "        ),\n    ]\n",
        )

    on_release(collision, "the release adds a GIN index", release)
    plant_app(collision, "zzz_search")
    plant_initial(collision, "zzz_search", "Document", "document_recency")
    collision.write(
        "apps/zzz_search/migrations/0002_document_name_gin.py",
        "from django.contrib.postgres.indexes import GinIndex\n"
        "from django.db import migrations\n\n\n"
        "class Migration(migrations.Migration):\n"
        '    dependencies = [("zzz_search", "0001_initial")]\n\n    operations = [\n'
        '        migrations.AddIndex(\n            model_name="document",\n'
        '            index=GinIndex(fields=["name"], name="note_name_gin_zzz"),\n'
        "        ),\n    ]\n",
    )
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: index note_name_gin_zzz — yours"
        " (apps/zzz_search/migrations/0002_document_name_gin.py) vs v0.2.0"
        " (apps/zzz_notes/migrations/0002_note_name_gin.py)" in text
    )
    assert "collisions: labels=0 tables=0 indexes=1 constraints=0 kinds=0" in text
    assert len(collision_lines(text)) == 1


def test_a_model_named_like_a_release_model_collides_on_its_kind(collision: World) -> None:
    plant_app(collision, "zzz_crm")
    plant_initial(collision, "zzz_crm", "Note", "crm_note_recency")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: kind note — yours (apps/zzz_crm · Note) vs v0.2.0 (apps/zzz_notes · Note)"
        in text
    )
    assert "collisions: labels=0 tables=0 indexes=0 constraints=0 kinds=1" in text
    assert len(collision_lines(text)) == 1
    assert KIND_REMEDY in text
    collision.write(
        "apps/zzz_crm/models.py", 'class Note(TenantScopedModel):\n    authz_kind = "crm_note"\n'
    )
    said = collision.against("--against", "v0.2.0")
    assert said.rc == 0, said.text()
    assert "collisions: none against v0.2.0" in said.text()
    collision.write(
        "apps/zzz_crm/models.py",
        "class Note(TenantScopedModel):\n"
        '    authz_kind: ClassVar[str] = "crm_note"  # its own word\n',
    )
    said = collision.against("--against", "v0.2.0")
    assert said.rc == 0, said.text()
    assert "collisions: none against v0.2.0" in said.text()


def test_no_against_prints_not_measured_and_changes_no_verdict(collision: World) -> None:
    plant_app(collision, "zzz_notes")
    plant_initial(collision, "zzz_notes", "Note", "note_recency", "note_zzz_unique")
    said = collision.against()
    text = said.text()
    assert said.rc == 0, text
    assert "collisions: not measured (no --against <release ref>)" in text
    assert not collision_lines(text)
    assert "\n== CLEAN" in text
    said = collision.census("--if-declared")
    assert said.rc == 0, said.text()
    assert "SKIPPED" in said.text()
    assert "collisions: not measured (no --against <release ref>)" in said.text()


def test_an_unresolvable_against_is_exit_2_naming_the_ref(collision: World) -> None:
    said = collision.against("--against", "zzz_nope")
    text = said.text()
    assert said.rc == 2
    assert "zzz_nope" in text
    assert "git fetch template --tags" in text
    assert "collisions: none" not in text
    assert collision.against("--against").rc == 2


def test_the_reserved_prefix_is_a_pair_in_waiting(collision: World) -> None:
    plant_app(collision, "djb_zzz")
    plant_initial(collision, "djb_zzz", "Reserved", "reserved_recency")
    said = collision.against("--against", "v0.2.0")
    assert said.rc == 2, said.text()
    assert (
        "collision: reserved prefix djb_ — apps/djb_zzz (yours); djb_ is the template's"
        " namespace for its platform apps" in said.text()
    )
    shutil.rmtree(collision.repo / "apps/djb_zzz")
    plant_app(collision, "zzz_djb")
    plant_initial(collision, "zzz_djb", "Reserved", "reserved_recency")
    said = collision.against("--against", "v0.2.0")
    assert said.rc == 0, said.text()
    assert "reserved prefix" not in said.text()
    assert "collisions: none against v0.2.0" in said.text()


def test_an_app_with_no_migrations_is_counted_unparsed(collision: World) -> None:
    plant_app(collision, "zzz_nomig")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 0, text
    assert "unparsed: apps/zzz_nomig (yours)" in text
    assert "yours parsed=1 unparsed=1" in text
    assert "collisions: none against v0.2.0" in text


# --- the mounts and the tags ---------------------------------------------------------------------


def plant_api(w: World, app: str, prefix: str | None, tag: str | None, *paths: str) -> None:
    """A minimal api.py: a `PREFIX` line unless None, one `Router(...)`, one route per path."""
    lines = ["from ninja import Router", ""]
    if prefix is not None:
        lines += [f'PREFIX = "{prefix}"', ""]
    lines.append("router = Router()" if tag is None else f'router = Router(tags=["{tag}"])')
    for path in paths:
        lines += ["", "", f'@router.get("{path}")', "def zzz_route(request):", "    return {}"]
    w.write(f"apps/{app}/api.py", "\n".join(lines) + "\n")


def release_api(w: World, prefix: str | None, tag: str | None, *paths: str) -> None:
    """The same api.py on the release's platform app, committed and re-tagged."""
    on_release(
        w,
        "the release's platform app mounts a router",
        lambda: plant_api(w, "zzz_notes", prefix, tag, *paths),
    )


def test_a_release_mount_and_tag_your_app_also_spells_is_a_pair_each(collision: World) -> None:
    release_api(collision, "notes", "notes", "/")
    plant_app(collision, "zzz_crm")
    plant_api(collision, "zzz_crm", "notes", "notes", "/")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: mount notes — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)"
        in text
    )
    assert (
        "collision: tag notes — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)"
        in text
    )
    assert "reserved=0 mounts=1 tags=1" in text
    assert len(collision_lines(text)) == 2
    assert text.count(MOUNT_REMEDY) == 1
    assert text.count(TAG_REMEDY) == 1


def test_a_root_route_on_the_release_mount_is_a_mount_pair(collision: World) -> None:
    release_api(collision, "notes", "notes", "/")
    plant_app(collision, "zzz_crm")
    plant_api(
        collision, "zzz_crm", "", "crm_notes", "/", "/notes/", "/notes/{note_id}/", "/{row_id}/"
    )
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: mount notes — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)"
        in text
    )
    assert "reserved=0 mounts=1 tags=0" in text
    assert len(collision_lines(text)) == 1


def test_a_sub_router_on_the_release_mount_is_a_mount_pair(collision: World) -> None:
    release_api(collision, "notes", "notes", "/")
    plant_app(collision, "zzz_crm")
    collision.write(
        "apps/zzz_crm/api.py",
        'from ninja import Router\n\nPREFIX = ""\n\nlinks = Router(tags=["crm_links"])\n'
        'router = Router()\nrouter.add_router("/notes/", links)\n',
    )
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: mount notes — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)"
        in text
    )
    assert "reserved=0 mounts=1 tags=0" in text
    assert len(collision_lines(text)) == 1


def test_an_app_with_no_prefix_mounts_at_its_label(collision: World) -> None:
    release_api(collision, "zzz_crm", "notes", "/")
    plant_app(collision, "zzz_crm")
    plant_api(collision, "zzz_crm", None, "crm_notes", "/")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: mount zzz_crm — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)"
        in text
    )
    assert "labels=0 " in text
    assert "reserved=0 mounts=1 tags=0" in text
    assert len(collision_lines(text)) == 1


def test_a_product_mount_or_tag_under_djb_is_the_reserved_line(collision: World) -> None:
    release_api(collision, "notes", "notes", "/")
    plant_app(collision, "zzz_crm")
    plant_api(collision, "zzz_crm", "djb_x", "crm_notes", "/")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert "collision: reserved prefix djb_ — mount djb_x in apps/zzz_crm/api.py (yours)" in text
    assert "reserved=1 mounts=0 tags=0" in text
    assert MOUNT_REMEDY in text
    plant_api(collision, "zzz_crm", "crm-notes", "djb_x", "/")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert "collision: reserved prefix djb_ — tag djb_x in apps/zzz_crm/api.py (yours)" in text
    assert "reserved=1 mounts=0 tags=0" in text
    assert TAG_REMEDY in text
    plant_api(collision, "zzz_crm", "x_djb", "crm_notes", "/")
    said = collision.against("--against", "v0.2.0")
    assert said.rc == 0, said.text()
    assert "reserved prefix" not in said.text()
    assert "collisions: none against v0.2.0" in said.text()


def test_a_mount_and_a_tag_of_your_own_are_no_collision(collision: World) -> None:
    release_api(collision, "notes", "notes", "/")
    plant_app(collision, "zzz_crm")
    plant_api(collision, "zzz_crm", "crm-notes", "crm_notes", "/")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 0, text
    assert "collisions: none against v0.2.0" in text
    assert "reserved=0 mounts=0 tags=0" in text
    assert not collision_lines(text)


# --- the heading and the schema name -------------------------------------------------------------


def release_titled(w: World) -> None:
    """The release's platform app titles its tag "Notes" and publishes a `NoteOut`."""

    def plant() -> None:
        w.write(
            "apps/zzz_notes/api.py",
            "\n".join(
                (
                    "from ninja import Router",
                    "",
                    "from apps.core.api.docs import Tag",
                    "",
                    'PREFIX = "notes"',
                    "",
                    "TAGS = {",
                    '    "notes": Tag(',
                    '        "Notes",',
                    '        "The release\'s notes.",',
                    "    ),",
                    "}",
                    "",
                    'router = Router(tags=["notes"])',
                )
            )
            + "\n",
        )
        w.write(
            "apps/zzz_notes/schemas.py",
            "from ninja import Schema\n\n\nclass NoteOut(Schema):\n    body: str\n",
        )

    on_release(w, "the release's platform app titles its tag and publishes a schema", plant)


def plant_titled(w: World, display: str, schema: str) -> None:
    """YOUR app on a mount and a tag of its own, its tag titled `display`, defining `schema`."""
    plant_app(w, "zzz_crm")
    w.write(
        "apps/zzz_crm/api.py",
        "\n".join(
            (
                "from ninja import Router, Schema",
                "",
                "from apps.core.api.docs import Tag",
                "",
                'PREFIX = "crm-notes"',
                "",
                f'TAGS = {{"crm_notes": Tag("{display}", "Your own notes.")}}',
                "",
                'router = Router(tags=["crm_notes"])',
                "",
                "",
                f"class {schema}(Schema):",
                "    body: str",
            )
        )
        + "\n",
    )


def test_a_display_title_the_release_carries_is_a_title_pair(collision: World) -> None:
    release_titled(collision)
    plant_titled(collision, "Notes", "CrmNoteOut")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: title Notes — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)"
        in text
    )
    assert "mounts=0 tags=0 titles=1 schemas=0 roads=0" in text
    assert len(collision_lines(text)) == 1
    assert text.count(TITLE_REMEDY) == 1
    assert "Tag(" not in "".join(line for line in text.splitlines() if "unparsed: " in line)


def test_a_display_title_of_your_own_is_no_collision(collision: World) -> None:
    release_titled(collision)
    plant_titled(collision, "Field notes", "CrmNoteOut")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 0, text
    assert "collisions: none against v0.2.0" in text
    assert "tags=0 titles=0 schemas=0" in text
    assert not collision_lines(text)


def test_a_schema_name_the_release_defines_is_a_schema_pair(collision: World) -> None:
    release_titled(collision)
    plant_titled(collision, "Field notes", "NoteOut")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 2, text
    assert (
        "collision: schema NoteOut — yours (apps/zzz_crm/api.py) vs v0.2.0"
        " (apps/zzz_notes/schemas.py)" in text
    )
    assert "tags=0 titles=0 schemas=1 roads=0" in text
    assert len(collision_lines(text)) == 1
    assert text.count(SCHEMA_REMEDY) == 1


def test_a_schema_name_of_your_own_is_no_collision(collision: World) -> None:
    release_titled(collision)
    plant_titled(collision, "Field notes", "CrmNoteOut")
    collision.append(
        "apps/zzz_crm/api.py",
        '\n\nclass NoteOutHelper:\n    """Not a schema: a nested name is still its own."""\n',
    )
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 0, text
    assert "collisions: none against v0.2.0" in text
    assert "titles=0 schemas=0" in text
    assert not collision_lines(text)


# --- the roads: a job the release marks, against a job one of yours marks ------------------------

#: Rule 84's valve word, assembled so no line of this module is itself a valve.
VALVE = "rule" + "-84"
ROAD_REMEDY = divergence.COLL_ROAD_REMEDY
RELEASE_ROAD = (
    '"""The refusal grammar."""',
    "",
    "from apps.core.roads import road",
    "",
    "",
    '@road("refuse", example="apps/core/exceptions.py::wire_refusal")',
    "def wire_refusal(exc):",
    '    """The only builder of a refusal body."""',
    "    return {}",
)


def release_road(w: World) -> None:
    """The release's platform app marks the refusal road."""
    on_release(
        w,
        "the release marks the refusal road",
        lambda: w.write("apps/core/exceptions.py", "\n".join(RELEASE_ROAD) + "\n"),
    )


def plant_road(w: World, app: str, job: str, reason: str = "") -> None:
    """The product's own app marks a road for `job`, under the valve when `reason` is given."""
    lines = ['"""The product\'s own refusals."""', "", "from apps.core.roads import road", "", ""]
    if reason:
        lines.append(f"# {VALVE}: {reason}")
    lines += [
        f'@road("{job}", example="apps/{app}/api.py::order_refusal")',
        "def order_refusal(exc):",
        '    """Our own refusal body."""',
        "    return {}",
    ]
    w.write(f"apps/{app}/api.py", "\n".join(lines) + "\n")


def test_a_product_road_for_a_job_the_release_marks_is_a_collision(collision: World) -> None:
    release_road(collision)
    plant_road(collision, "zzz_orders", "refuse")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    pair = (
        "collision: road refuse — yours (apps/zzz_orders/api.py) vs v0.2.0"
        " (apps/core/exceptions.py)"
    )
    lines = text.splitlines()
    assert said.rc == 2, text
    assert pair in lines
    assert lines[lines.index(pair) + 1] == f"   {ROAD_REMEDY}"
    assert "tags=0 titles=0 schemas=0 roads=1 · release v0.2.0" in text
    assert len(collision_lines(text)) == 1
    plant_road(collision, "zzz_orders", "refuse", "our refusal body stays until the platform road")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 0, text
    assert (
        "   kept: road refuse — yours (apps/zzz_orders/api.py) beside v0.2.0"
        " (apps/core/exceptions.py), declared by the valve above your marker" in text.splitlines()
    )
    assert "tags=0 titles=0 schemas=0 roads=0 · release v0.2.0" in text
    assert "collisions: none against v0.2.0" in text
    assert not collision_lines(text)


def test_a_product_road_for_a_job_of_its_own_is_no_collision(collision: World) -> None:
    release_road(collision)
    plant_road(collision, "zzz_orders", "order_intake")
    collision.write(
        "scripts/local/export.sh",
        "# road: order_export — the product exports its orders"
        " · example: scripts/local/export.sh::order_export\norder_export() {\n    :\n}\n",
    )
    collision.write("apps/core/exceptions.py", "\n".join(RELEASE_ROAD) + "\n")
    collision.commit("the base carries the platform's road", "apps/core/exceptions.py")
    collision.tag("v0.1.0")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 0, text
    assert "collisions: none against v0.2.0" in text
    assert "tags=0 titles=0 schemas=0 roads=0 · release v0.2.0" in text
    assert not collision_lines(text)
    assert "kept: " not in text


def test_a_road_marker_that_will_not_read_is_unparsed_never_a_skip(collision: World) -> None:
    release_road(collision)
    plant_road(collision, "zzz_orders", "Not_A_Job")
    said = collision.against("--against", "v0.2.0")
    text = said.text()
    assert said.rc == 0, text
    assert (
        "   unparsed: apps/zzz_orders/api.py (yours) — a road marker that does not split into a"
        " job and its contract; its job was not read" in text.splitlines()
    )


def test_roads_prints_every_marker_and_refuses_the_other_flags(collision: World) -> None:
    release_road(collision)
    collision.write("apps/core/exceptions.py", "\n".join(RELEASE_ROAD) + "\n")
    plant_road(collision, "zzz_orders", "refuse", "kept beside the platform's")
    said = collision.census("--roads")
    rows = [r for r in said.text().splitlines()[1:] if "\tapps/" in r]
    assert said.rc == 0, said.text()
    assert rows == [
        "road\trefuse\tapps/core/exceptions.py",
        "road\trefuse\tapps/zzz_orders/api.py\tkept",
    ]
    assert collision.census("--roads", "--if-declared").rc == 2
    assert collision.census("--roads", "--against", "v0.2.0").rc == 2


def test_roads_over_is_the_shell_census_roads_class(collision: World) -> None:
    release_road(collision)
    plant_road(collision, "zzz_orders", "refuse")
    root = str(collision.repo)
    said = collision.census("--roads-over", "v0.2.0", "all", root)
    assert said.rc == 0
    assert [r for r in said.text().splitlines() if "\tapps/" in r] == [
        "road\trefuse\tapps/core/exceptions.py"
    ]
    assert "road\tcould_not_look\tscripts/gate_refuse.sh" in said.text().splitlines()
    said = collision.census("--roads-over", "tree", "yours", root)
    assert said.rc == 0
    assert said.text().splitlines() == ["road\trefuse\tapps/zzz_orders/api.py"]
    assert collision.census("--roads-over", "tree", "nobody", root).rc == 2


# --- the facade and the worked example: two ownership facts -------------------------------------


def _with_facade_and_worked_example(w: World) -> str:
    """Add `pilecap/` and a worked example to the fixture's v0.1.0; the base's commit."""
    w.write("pilecap/__init__.py", '"""the facade"""\n')
    w.write("apps/example/models.py", "# the worked example\n")
    w.write("frontend/src/copy/widget.ts", "export const widget = {};\n")
    w.commit("the facade and the worked example at v0.1.0")
    w.tag("v0.1.0")
    return base_of(w)


def test_the_facade_and_the_worked_example_are_classified() -> None:
    assert divergence.ownership_of("pilecap/__init__.py", ["R1"], ["core"]) == "template"
    for path in (
        "apps/example/models.py",
        "apps/example_portal/api.py",
        "frontend/src/screens/widget/list.tsx",
        "frontend/src/copy/customer.ts",
    ):
        assert divergence.ownership_of(path, divergence.rule_ids(path), ["core", "example"]) == (
            "worked-example"
        ), path
    assert divergence.ownership_of("apps/zzz_product_app/x.py", ["R1"], ["core"]) == "product"


def test_an_edit_to_the_facade_is_a_divergence(repo: World) -> None:
    base = _with_facade_and_worked_example(repo)
    repo.append("pilecap/__init__.py", "x = 1\n")
    repo.commit("a product edits the facade")
    said = repo.census(base=base)
    assert said.rc == 1, said.text()
    assert "   divergence: pilecap/__init__.py · +1-0 · " in said.text()


def test_deleting_the_worked_example_is_not_a_divergence(repo: World) -> None:
    base = _with_facade_and_worked_example(repo)
    repo.git("rm", "-q", "apps/example/models.py", "frontend/src/copy/widget.ts")
    repo.commit("a product deletes the worked example")
    said = repo.census(base=base)
    assert said.rc == 0, said.text()
    assert "   deleted worked example: 2 path(s) — not a divergence" in said.text()
    assert "divergence: apps/example" not in said.text()


def test_an_edit_to_the_worked_example_is_a_divergence(repo: World) -> None:
    base = _with_facade_and_worked_example(repo)
    repo.append("apps/example/models.py", "# a product's edit\n")
    repo.commit("a product edits the worked example")
    said = repo.census(base=base)
    assert said.rc == 1, said.text()
    assert "   divergence: apps/example/models.py · +1-0 · " in said.text()
    assert "   worked     2 worked-example paths" in said.text()


def _codeowned(path: str, lines: list[str]) -> bool:
    """Whether the last CODEOWNERS pattern matching `path` names an owner (the generated forms)."""
    owner = False
    for line in lines:
        pattern, _, who = line.partition(" ")
        if pattern.startswith("**/") or pattern.startswith("*."):
            hit = fnmatch.fnmatchcase(path, pattern.removeprefix("**/")) or fnmatch.fnmatchcase(
                path, pattern
            )
        elif pattern.endswith("/"):
            hit = path.startswith(pattern[1:])
        else:
            hit = path == pattern[1:]
        if hit:
            owner = bool(who.strip())
    return owner


def test_codeowners_outside_the_tree_is_written_and_named_absolute(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "CODEOWNERS"
    assert divergence.write_codeowners([str(target)], ROOT) == 0
    assert target.read_text() == divergence.codeowners_text(ROOT)
    assert capsys.readouterr().out.strip() == f"codeowners: wrote {target.resolve()}"


def test_codeowners_to_an_unwritable_target_is_could_not_look(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "file").write_text("")
    assert divergence.write_codeowners([str(tmp_path / "file" / "CODEOWNERS")], ROOT) == 2
    assert "could not write" in capsys.readouterr().err


def test_the_codeowners_template_is_the_classifiers_roots_both_ways() -> None:
    """Template-owned is code-owned and code-owned is template-owned; the file is byte-equal."""
    shipped = (ROOT / divergence.CODEOWNERS_TEMPLATE).read_text()
    assert shipped == divergence.codeowners_text(ROOT), (
        "regenerate: python -m quality.djb.rituals.divergence --codeowners"
    )
    lines = [line for line in shipped.splitlines() if line and not line.startswith("#")]
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    platform = divergence.platform_apps(ROOT)
    rules = divergence.rules_for(tracked)
    owned_kinds = ("template", "worked-example")
    template = {p for p in tracked if divergence.ownership_of(p, rules[p], platform) in owned_kinds}
    owned = {p for p in tracked if _codeowned(p, lines)}
    assert template - owned == set(), "template-owned paths no code owner reviews"
    assert owned - template == set(), "code-owned paths the classifier calls the product's"
    assert len(template) > 1000
