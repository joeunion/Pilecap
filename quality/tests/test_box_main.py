"""The entry's cases: the dispatcher, `pool`'s launch arm, the censuses over the package."""

from __future__ import annotations

import ast
import hashlib
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quality.djb.box.core import SUBCOMMANDS, SYNOPSIS, commands
from quality.tests.fixtures.box_world import OWNER, SUBJECT, World
from quality.tests.test_box_census import census_rows, pool_ready
from quality.tests.test_box_launch import twin
from quality.tests.test_box_push import ROOT, SHELL, fresh

pytestmark = pytest.mark.drives(
    "quality/djb/box/__main__.py",
    "quality/djb/box/core.py",
    "scripts/verifier_box.sh",
    "quality/djb/rituals/verify_start.py",
)

PACKAGE = ROOT / "quality" / "djb" / "box"
IMAGE_SIDE = ("deploy/verifier", "deploy/iam")
TESTS = (
    "quality/tests/test_box_*.py",
    ":!quality/tests/test_box_bank.py",  # pm_push.sh's cases; that drive's census owns its fixture
    "quality/tests/fixtures/box_world.py",
)
UNTOUCHED = ("scripts/gate_lease.sh", "scripts/setup.sh", ".env.example")
EARLY_EXIT = re.compile(
    r"\|[ \t]*(head([ \t]|$)|grep[^|]*-[A-Za-z]*q([ \t]|$)|grep[^|]*-m[ \t]"
    r"|awk[^|]*exit|sed -n[^|]*q)"
)
PYTHON = re.compile(r"(^|[^A-Za-z0-9_])python3?([^A-Za-z0-9_]|$)")
DATE_FORMAT = re.compile(r"date[^|]*[+-]%[a-zA-Z]")
REGION = re.compile(
    r"\b(us|eu|ap|ca|sa|me|af|il)-(gov-)?(east|west|north|south|central|northeast|northwest"
    r"|southeast|southwest)-[0-9]\b"
)
HOST_KEY_SITES = {
    "transport.py": {"ssh_argv", "scp_argv"},
    "push.py": {"scp_argv"},
    "harvest.py": {"scp_argv"},
    "shallow.py": {"push_the_tree_shallow"},
    "bake.py": {"bake_keep_hands_over"},
}


def tracked(*specs: str) -> list[Path]:
    """The tracked files under `specs` (paths or globs), read through git."""
    done = subprocess.run(
        ["git", "ls-files", "--", *specs], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [ROOT / line for line in done.stdout.splitlines()]


def modules() -> list[Path]:
    """Every module of the package."""
    return sorted(PACKAGE.glob("*.py"))


def strings(path: Path) -> list[tuple[int, str, str]]:
    """Every string a module carries that is not a docstring: (line, enclosing def, text)."""
    tree = ast.parse(path.read_text())
    docs = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    found: list[tuple[int, str, str]] = []

    def visit(node: ast.AST, owner: str) -> None:
        if isinstance(node, ast.FunctionDef):
            owner = node.name
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                str(part.value) if isinstance(part, ast.Constant) else "{}" for part in node.values
            )
            found.append((node.lineno, owner, text))
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            found.append((node.lineno, owner, node.value))
            return
        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    visit(tree, "")
    return found


def shell_code(path: Path) -> list[tuple[int, str]]:
    """A shell file's lines with comments dropped, continuation lines joined; (first line, text)."""
    joined: list[tuple[int, str]] = []
    buf, start = "", 0
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = re.sub(r"[ \t]*#.*$", "", raw)
        buf, start = (line, n) if not buf else (f"{buf} {line}", start)
        if re.search(r"\|[ \t]*$", line):
            continue
        joined.append((start, buf))
        buf = ""
    return joined


def footprint(root: Path) -> dict[str, str]:
    """The bytes of the files the client promises never to touch, by sha256, or `absent`."""
    found = {}
    for name in UNTOUCHED:
        path = root / name
        found[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"
    return found


def delta(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """`<file>  before <x> vs after <y>` for every file that moved."""
    return [
        f"{name}  before {before[name]} vs after {after[name]}"
        for name in UNTOUCHED
        if before[name] != after[name]
    ]


def iso_utc(epoch: int) -> str:
    """A second implementation of the client's ISO arithmetic: the standard library's."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the dispatcher ----------------------------------------------------------------------


def test_the_usage_is_the_shells_byte_for_byte(world: World) -> None:
    twin(world)
    assert world.rc == 2, world.report()
    assert world.out.splitlines()[2:] == [f" {line}" for line in SYNOPSIS]


def test_an_unknown_subcommand_or_flag_is_exit_2(world: World) -> None:
    twin(world, "nonsense")
    assert world.rc == 2, world.report()
    world.up_ready()
    twin(world, "up", "--for", "X", "--nonsense")
    assert world.rc == 2, world.report()
    assert not (world.rec / "aws.ops").exists()
    dispatched = set(SUBCOMMANDS.split()) | set(commands())
    synopsis = {line.split()[1] for line in SYNOPSIS}
    assert dispatched, "no dispatcher arms read out of the package — the census lost its subject"
    assert dispatched <= synopsis, sorted(dispatched - synopsis)
    assert set(commands()) <= set(SUBCOMMANDS.split()), sorted(
        set(commands()) - set(SUBCOMMANDS.split())
    )


@pytest.mark.parametrize("door", ["shell", "module"])
def test_a_piped_stdout_is_refused(world: World, door: str) -> None:
    argv = ["bash", str(SHELL)] if door == "shell" else list(SUBJECT)
    done = subprocess.run(
        [*argv, "census"],
        cwd=ROOT,
        env=world.env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    assert done.returncode == 2, done.stdout
    assert not (world.rec / "aws.ops").exists()


# --- pool's launch arm ------------------------------------------------------------------


def test_pool_launches_the_difference_with_the_pool_tags(world: World) -> None:
    pool_ready(world)
    world.ans("ec2_run-instances.1", "i-p1")
    world.ans("ec2_run-instances.2", "i-p2")
    twin(world, "pool", "--want", "2")
    assert world.rc == 0, world.report()
    assert world.op_count("ec2 run-instances") == 2
    calls = [world.nth_call_of("run-instances", n) for n in (1, 2)]
    assert all("Key=djb:for,Value=pool" in call for call in calls)
    assert all("Key=djb:price,Value=0.2085" in call for call in calls)
    assert "pool: 0 warm · 2 launched · 0 trimmed · $0.4170/h" in world.out
    assert all((world.vhome / box / "id_ed25519").is_file() for box in ("i-p1", "i-p2"))


def test_a_pool_launch_carries_its_idle_threshold(world: World) -> None:
    pool_ready(world)
    world.ans("ec2_run-instances", "i-p1")
    twin(world, "pool", "--want", "1", "--idle", "7")
    assert world.rc == 0, world.report()
    call = world.nth_call_of("run-instances", 1)
    assert "/etc/verifier/idle-minutes" in call
    assert 'content: "7"' in call
    assert "Key=djb:idle,Value=7" in call


# --- the wrapper's censuses, over the package and the wrapper file ----------------------


def test_no_early_exit_reader_follows_a_pipe_in_this_wrapper() -> None:
    hits = [f"{SHELL.name}:{n}: {text}" for n, text in shell_code(SHELL) if EARLY_EXIT.search(text)]
    for path in modules():
        hits += [
            f"{path.name}:{n}: {text}" for n, _, text in strings(path) if EARLY_EXIT.search(text)
        ]
    assert not hits, "a reader that leaves before its producer finishes:\n" + "\n".join(hits)


def test_no_product_name_account_or_region_is_hard_coded() -> None:
    slug = re.compile("pile" + "cap" + "[-/]")
    account = re.compile(r"[^0-9][0-9]{12}[^0-9]")
    scope = [SHELL, *modules(), *tracked(*IMAGE_SIDE), *tracked(*TESTS)]
    assert len(scope) > len(modules()) + 1, scope
    slugs, accounts = [], []
    for path in scope:
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            where = f"{path.relative_to(ROOT)}:{n}"
            slugs += [where] if slug.search(line) else []
            accounts += [where] if account.search(line) else []
    assert not slugs, slugs
    assert not accounts, accounts
    assert "DJB_DEPLOY_NAMESPACE" in (PACKAGE / "core.py").read_text()


def test_the_only_excused_region_is_the_drives_own_fixture() -> None:
    subject = [SHELL, *modules(), *tracked(*IMAGE_SIDE)]
    hits = []
    for path in subject:
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            hits += [f"{path.relative_to(ROOT)}:{n}: {line}"] if REGION.search(line) else []
    assert not hits, hits
    fixture = []
    for path in tracked(*TESTS):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if REGION.search(line) and "us-west-2" not in line:
                fixture.append(f"{path.relative_to(ROOT)}:{n}: {line}")
    assert not fixture, fixture


def test_the_host_key_posture_is_argued_where_it_is_used() -> None:
    sites: dict[str, set[str]] = {}
    for path in modules():
        for _, owner, text in strings(path):
            if "StrictHostKeyChecking=no" in text:
                sites.setdefault(path.name, set()).add(owner)
    assert sites, "no host-key option in the package — the census lost its subject"
    assert sites == HOST_KEY_SITES, sites
    for name, owners in HOST_KEY_SITES.items():
        tree = ast.parse((PACKAGE / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in owners:
                body = ast.unparse(node)
                for want in ("UserKnownHostsFile=/dev/null", "proxy_command()"):
                    assert want in body, f"{name}::{node.name} lacks {want}"
    transport = (PACKAGE / "transport.py").read_text()
    for reason in ("Session Manager", "new every launch"):
        assert reason in transport, f"transport.py does not argue the posture: {reason!r}"


def test_the_wrapper_reaches_python_only_through_the_checkout(world: World) -> None:
    shell = [(n, text) for n, text in shell_code(SHELL) if PYTHON.search(text)]
    assert all("checkout_python" in text for _, text in shell), shell
    spoken = [
        f"{path.name}:{n}: {text}"
        for path in modules()
        for n, _, text in strings(path)
        if PYTHON.search(text)
    ]
    assert not spoken, spoken
    formats = [
        f"{path.name}:{n}: {text}"
        for path in [SHELL, *modules()]
        for n, text in (
            shell_code(path) if path == SHELL else [(n, t) for n, _, t in strings(path)]
        )
        if DATE_FORMAT.search(text) and not re.search(r"date \+%s", text)
    ]
    assert not formats, formats
    wrong = []
    for want in (1704067199, 1709164800, 1755000000, 1767225600, 2145916800):
        fresh(world).up_ready()
        world.clock.file.write_text(f"{want}\n")
        twin(world, "up", "--for", "X", "--ttl", "1")
        call = world.nth_call_of("run-instances", 1)
        tag = re.search(r"Key=djb:expires,Value=([0-9TZ:-]+)", call)
        got = tag.group(1) if tag else ""
        wrong += [] if got == iso_utc(want + 3600) else [f"epoch→iso {want}: {got}"]
    for want in (1704067199, 1709164800, 1755000000, 1767225600):
        for offset, rc in ((-60, 1), (60, 0)):
            fresh(world)
            world.clock.file.write_text(f"{want}\n")
            row = ("i-x1", "c7g.4xlarge", "verifier", OWNER, iso_utc(want + offset))
            census_rows(world, (*row, iso_utc(want - 600), "ami-v1"))
            twin(world, "census")
            wrong += [] if world.rc == rc else [f"census at {want}{offset:+}: exit {world.rc}"]
    assert not wrong, wrong


def test_nothing_this_wrapper_promised_not_to_touch_moved(world: World, tmp_path: Path) -> None:
    before = footprint(ROOT)
    acts = 0
    world.up_ready()
    for args in (("up", "--for", "X"), ("census",), ("ceiling",), ("down", "i-up1")):
        twin(world, *args)
        acts += 1
    assert acts >= 1
    assert delta(before, footprint(ROOT)) == [], delta(before, footprint(ROOT))
    victim = tmp_path / "victim"
    (victim / "scripts").mkdir(parents=True)
    for name in UNTOUCHED:
        shutil.copy(ROOT / name, victim / name)
    planted = footprint(victim)
    with (victim / "scripts" / "setup.sh").open("a") as out:
        out.write("\n# a wrapper that wrote where it promised not to\n")
    assert any(line.startswith("scripts/setup.sh") for line in delta(planted, footprint(victim)))
    (victim / ".env.example").unlink()
    assert any(
        line.startswith(".env.example  before") and line.endswith("vs after absent")
        for line in delta(planted, footprint(victim))
    )
    remedy = "core.hooksPath=scripts/githooks"
    assert any(remedy in text for path in modules() for _, _, text in strings(path))
    ritual = (ROOT / "quality/djb/rituals/verify_start.py").read_text()
    assert '"config", "core.hooksPath", "scripts/githooks"' in ritual
