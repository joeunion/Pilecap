"""A fact two readers spell gives one reading: every reader agrees on the same edge inputs."""

# does-not-cover: a reader this table does not name — a new spelling joins its fact by hand.
# does-not-cover: the runbook's IAM policy resources for the repositories — only its step-19a loop.

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import boundary, scope
from quality.djb.rituals import divergence
from quality.partition import platform_apps_in
from quality.sdk import reference

pytestmark = pytest.mark.drives(
    "quality/partition.py",
    "quality/djb/scope.py",
    "quality/djb/rituals/divergence.py",
    "quality/djb/boundary.py",
    "quality/engine/rules.py",
    "deploy/stage.sh",
    "deploy/provision.sh",
    "deploy/iam/product_bootstrap.sh",
    "deploy/compose.yaml",
)

ROOT = Path(__file__).resolve().parents[2]

# --- platform_apps: the partition lockfile's list ----------------------------------------------

LOCK_HEAD = "# the lockfile\nversion: 1\nplatform_apps:\n"
LOCK_TAIL = "exclusions: []\n"
#: Edge spellings of a three-label list a hand might write.
LOCKS: dict[str, str] = {
    "plain": "  - accounts\n  - core\n  - events\n",
    "indented comment": "  - accounts\n  # the identity apps end here\n  - core\n  - events\n",
    "blank line": "  - accounts\n\n  - core\n  - events\n",
    "trailing comment": "  - accounts  # identity\n  - core\n  - events\n",
    "column-zero comment": "  - accounts\n# a note\n  - core\n  - events\n",
}


def _lock_root(tmp_path: Path, body: str) -> Path:
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/partition.yaml").write_text(LOCK_HEAD + body + LOCK_TAIL)
    return tmp_path


LOCK_READERS: dict[str, Callable[[Path], list[str]]] = {
    "partition.platform_apps_in": lambda root: platform_apps_in(
        (root / "quality/partition.yaml").read_text()
    ),
    "scope.platform_apps": lambda root: list(scope.platform_apps(root)),
    "divergence.platform_apps": divergence.platform_apps,
}

#: The day the dated rows below were written; the rung that fixes a reader deletes its row.
KNOWN_SINCE = "2026-10-19"
#: Known disagreements; a row whose reader agrees now reds until it is deleted.
KNOWN_LOCK_DISAGREEMENTS: frozenset[tuple[str, str]] = frozenset()


@pytest.mark.parametrize("probe", sorted(LOCKS))
def test_every_reader_of_platform_apps_reads_one_list(tmp_path: Path, probe: str) -> None:
    root = _lock_root(tmp_path, LOCKS[probe])
    readings = {name: sorted(read(root)) for name, read in LOCK_READERS.items()}
    truth = readings["partition.platform_apps_in"]
    assert truth == ["accounts", "core", "events"], f"the YAML reading itself moved: {truth}"
    for name, reading in readings.items():
        if (name, probe) in KNOWN_LOCK_DISAGREEMENTS:
            assert reading != truth, (
                f"{name} agrees on {probe!r} now — delete its row ({KNOWN_SINCE})"
            )
            continue
        assert reading == truth, f"{probe!r}: {name} reads {reading}, the YAML reads {truth}"


# --- the drawer namespace: "is this tree a product" --------------------------------------------

#: Every site that asks it in shell, with the anchor its `grep -Eq` line carries.
SHELL_SITES = (
    "deploy/stage.sh",
    ".github/workflows/ci.yml",
    ".github/workflows/proof-from-zero.yml",
)
_GREP = re.compile(r'grep -Eq "((?:[^"\\]|\\.)*rule_id_namespace(?:[^"\\]|\\.)*)"')
#: The spellings a drawer might carry; `None` is no drawer at all.
SPELLINGS: dict[str, str | None] = {
    "absent": None,
    "declare's": "rule_id_namespace: acme\n",
    "double-quoted": 'rule_id_namespace: "acme"\n',
    "single-quoted": "rule_id_namespace: 'acme'\n",
    "trailing comment": "rule_id_namespace: acme  # ours\n",
    "empty": "rule_id_namespace:\n",
    "empty string": 'rule_id_namespace: ""\n',
    "empty single-quoted": "rule_id_namespace: ''\n",
    "null": "rule_id_namespace: null\n",
    "tilde": "rule_id_namespace: ~\n",
    "no space": "rule_id_namespace:acme\n",
    "indented": "  rule_id_namespace: acme\n",
    "flow mapping": "{rule_id_namespace: acme}\n",
    "commented out": "# rule_id_namespace: acme\n",
}


def shell_pattern(path: str) -> str:
    """The ERE a site's `grep -Eq` asks, lifted from the file and unescaped as bash would."""
    found = _GREP.findall((ROOT / path).read_text())
    assert len(found) == 1, f"{path}: expected one drawer grep, found {len(found)}"
    return re.sub(r"\\(.)", r"\1", found[0])


def shell_reading(pattern: str, drawer: Path) -> str:
    done = subprocess.run(["grep", "-Eq", pattern, str(drawer)], capture_output=True)
    return "product" if done.returncode == 0 else "template"


def python_reading(text: str | None) -> str:
    try:
        return "product" if boundary.namespace_in(text) else "template"
    except CouldNotLook:
        return "refuse"


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
def test_the_shell_and_the_engine_read_one_drawer_namespace(tmp_path: Path, spelling: str) -> None:
    text = SPELLINGS[spelling]
    drawer = tmp_path / "rules.yaml"
    if text is not None:
        drawer.write_text(text)
    python = python_reading(text)
    for site in SHELL_SITES:
        shell = shell_reading(shell_pattern(site), drawer)
        assert shell == python or python == "refuse", (
            f"{spelling!r}: {site} reads {shell}, the engine reads {python} — a disagreement"
            " must fail closed: the engine refuses, and its exit 2 holds the product's gate"
        )


@pytest.mark.parametrize(
    "spelling", ["empty", "empty string", "empty single-quoted", "null", "tilde"]
)
def test_a_declared_empty_namespace_refuses(spelling: str) -> None:
    assert python_reading(SPELLINGS[spelling]) == "refuse", (
        f"{spelling!r}: the drawer declares the key with no namespace and the engine reads"
        f" {python_reading(SPELLINGS[spelling])} — a declared key names its namespace or refuses"
    )


# --- the image repositories ---------------------------------------------------------------------

NUMBERS = ("no", "one", "two", "three", "four", "five", "six", "seven")


def image_services() -> list[str]:
    done = subprocess.run(
        ["bash", "deploy/provision.sh", "image-services"], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, f"provision.sh image-services: {done.stderr}"
    return done.stdout.split()


def test_every_home_of_the_image_repositories_names_the_owners_list() -> None:
    owner = sorted(f"djb-{s}" for s in image_services())
    bootstrap = (ROOT / "deploy/iam/product_bootstrap.sh").read_text()
    made = re.search(r"^REPOSITORIES=\((.*)\)$", bootstrap, re.M)
    assert made, "product_bootstrap.sh: no REPOSITORIES=( … ) line"
    compose = (ROOT / "deploy/compose.yaml").read_text()
    runbook = (ROOT / "docs/runbooks/deploy.md").read_text()
    loop = re.search(r"^for repo in ((?:djb-\S+ ?)+); do$", runbook, re.M)
    assert loop, "deploy.md: no `for repo in djb-…` loop"
    homes = {
        "product_bootstrap.sh REPOSITORIES": sorted(re.findall(r"/(djb-[\w-]+)\"", made.group(1))),
        "compose.yaml x-image anchors": sorted(
            re.findall(r"^x-image-[\w-]+: &image-[\w-]+ .*?/(djb-[\w-]+):", compose, re.M)
        ),
        "deploy.md step 19a loop": sorted(loop.group(1).split()),
    }
    for home, names in homes.items():
        assert names == owner, f"{home} names {names}; `provision.sh image-services` names {owner}"


def test_the_deploying_page_counts_the_owners_images() -> None:
    word = NUMBERS[len(image_services())]
    page = reference.deploying_page(ROOT)
    said = re.findall(r"\bthe (\w+) image(?: repositories|s)\b", page)
    assert said, "the deploying page names no count of images"
    assert set(said) == {word}, f"the deploying page says {said}; image-services names {word}"
