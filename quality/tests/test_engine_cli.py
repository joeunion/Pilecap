"""The engine's narrowed self-test in a clone of HEAD: the shape it judges, and how it exits."""

# does-not-cover: the whole corpus — narrowed by default; DJB_SELFTEST_SHAPES_WHOLE_RUN asks for it.
# does-not-cover: a product's real template remote — the base is a synthetic tag in scratch.
# does-not-cover: rule 60's base-planting forms on a product tree with no declared base.

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.scratch import require_scratch
from quality.tests.test_engine_explain import (
    ROOT,
    Ran,
    World,
    clone_world,
    digest,
    drop_world_databases,
    moved_paths,
)

pytestmark = pytest.mark.drives("quality/engine/cli.py", "quality/gate.py")

PY = sys.executable
NARROWED = "selftest: narrowed to rule(s) 51, 60 — the legs, the seam, the budget canary and the censuses were not run; this is not the gate's verdict"  # noqa: E501
REFUSALS = ("PLANT REFUSED", "CANARY DEAD", "FALSE-POSITIVE", "COULD NOT LOOK", "POPULATION SHORT")
WHOLE = os.environ.get("DJB_SELFTEST_SHAPES_WHOLE_RUN", "")

FLOORS = r"""
import quality.gate as g

for rule in g.RULES:
    f = g.selftest_floor(rule)
    on = "on" if rule.get("enabled", True) else "off"
    counts = (int(f["canaries"]), int(f["negatives"]))
    print("floor", rule["id"], rule.get("name", ""), on, *counts, sep="\t")
"""


@dataclass(frozen=True)
class Floor:
    """One rule's plan: its name, whether it is on, and its recorded canary and negative counts."""

    name: str
    on: bool
    can: int
    neg: int

    def ok_line(self, rid: str) -> str:
        """The rule line of a narrowed run that judged every recorded form."""
        return f"  rule {rid} {self.name}: canaries {self.can}/{self.can} · negatives {self.neg}/{self.neg} — ok"  # noqa: E501


@dataclass
class ShapesWorld:
    """The clone at its synthetic release, the plan's floors, and the session's one self-test."""

    world: World
    version: str
    pre: str
    floors: dict[str, Floor]
    selftest: Ran
    wall: int
    before: str

    def narrowed(self, *rids: str) -> Ran:
        """`quality.gate --selftest --rule <id>…` in the world, through `looked`."""
        args = [a for rid in rids or ("51", "60") for a in ("--rule", rid)]
        return looked(self.world.run([PY, "-m", "quality.gate", "--selftest", *args]))

    def whole(self) -> Ran:
        """The engine's whole self-test in the world."""
        return looked(self.world.run([PY, "-m", "quality.gate", "--selftest"]))

    def reset(self) -> None:
        """Back to the synthetic release, every untracked path gone."""
        self.world.git("reset", "-q", "--hard", self.pre)
        self.world.git("clean", "-q", "-fd", "--", ".", ":!.env")


def looked(ran: Ran) -> Ran:
    """`ran` when the engine judged; `CouldNotLook` when it could not look and judged no rule."""
    if ran.rc in (0, 1):
        return ran
    if ran.rc == 2 and "selftest, by rule (fired/recorded · silent/recorded):" in ran.out:
        return ran
    first = next((ln for ln in ran.out.splitlines() if ln.startswith("  !! ")), "")
    raise CouldNotLook(ran.why(f"the engine could not look and judged no rule — {first}"))


def rule_line(ran: Ran, rid: str) -> str:
    """The run's line for `rid`, or ''."""
    return next((ln for ln in ran.out.splitlines() if ln.startswith(f"  rule {rid} ")), "")


@pytest.fixture(scope="session")
def shapes(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ShapesWorld]:
    """The world at its synthetic release, and ONE narrowed self-test of the template's shape."""
    home = require_scratch(tmp_path_factory.mktemp("engine-cli"), ROOT)
    world = clone_world(home, "world")
    plan = world.run([PY, "-c", FLOORS])
    if plan.rc != 0:
        raise CouldNotLook(plan.why("the world's plan would not read through quality.gate"))
    floors = {}
    for row in plan.out.splitlines():
        tag, rid, name, on, can, neg = (row.split("\t") + [""] * 6)[:6]
        if tag == "floor":
            floors[rid] = Floor(name, on == "on", int(can), int(neg))
    version = f"0.0.0rc{secrets.randbelow(2**32)}"
    (world.root / "TEMPLATE_VERSION").write_text(version + "\n")
    world.git("add", "--", "TEMPLATE_VERSION")
    if (world.root / "scripts" / "local" / "template-base").exists():
        world.git("rm", "-q", "--", "scripts/local/template-base")
    world.git("commit", "-q", "-m", f"world: the synthetic release v{version}")
    pre = world.git("rev-parse", "HEAD").strip()
    before = digest(world.root)
    built = ShapesWorld(world, version, pre, floors, Ran(0, "", world.logs), 0, before)
    import time

    start = time.monotonic()
    built.selftest = built.narrowed()
    built.wall = round(time.monotonic() - start)
    (home / "selftest-wall.txt").write_text(f"the session's narrowed --selftest: {built.wall}s\n")
    yield built
    drop_world_databases()
    moved = moved_paths(world.root, before)
    if moved:
        raise CouldNotLook(f"the world {world.root} was left moved: " + "; ".join(moved))


def test_a_dirty_template_owned_path_is_could_not_look_on_rule_60(shapes: ShapesWorld) -> None:
    """A dirty template-owned path is rule 60's could-not-look; a committed tree judges it all."""
    target = shapes.world.root / "scripts" / "db.sh"
    saved = target.read_bytes()
    target.write_bytes(
        saved + b"\n# W-T: an uncommitted edit, the builder's own and no product's\n"
    )
    try:
        ran = shapes.narrowed("60")
    finally:
        target.write_bytes(saved)
    cause = (
        "the tree is dirty on a template-owned path outside the plants: scripts/db.sh — commit or "
        "stash it; a base-planting form cannot tell your edit from a product's"
    )
    sixty = shapes.floors["60"]
    assert ran.rc == 2, ran.why("W-T dirty: the narrowed self-test did not exit 2")
    line = rule_line(ran, "60")
    assert line.startswith(f"  rule 60 {sixty.name}: canaries ") and line.endswith(
        f" — COULD NOT LOOK ({cause})"
    ), ran.why(f"W-T dirty: rule 60's line is {line!r}")
    assert "FALSE-POSITIVE" not in ran.out, ran.why("the form judged your edit as its own finding")
    assert "  !! rule 60: COULD NOT LOOK — " in ran.out, ran.why("no ENFORCEMENT BROKEN line")
    clean = shapes.selftest
    assert clean.rc == 0, clean.why("W-T committed: the narrowed self-test did not exit 0")
    lines = clean.out.splitlines()
    assert "selftest: template base — none declared (the template's own shape)" in lines, clean.why(
        "W-T committed: not judged on the template's own shape"
    )
    assert sixty.ok_line("60") in lines, clean.why(f"rule 60 is {rule_line(clean, '60')!r}")


def test_a_django_rule_narrowed_alone_judges_every_form(shapes: ShapesWorld) -> None:
    """Rule 41 narrowed alone judges every Django form inside the whole corpus's probe app."""
    ran = shapes.narrowed("41")
    assert ran.rc == 0, ran.why("rule 41 alone did not exit 0")
    assert shapes.floors["41"].ok_line("41") in ran.out.splitlines(), ran.why(
        f"rule 41 is {rule_line(ran, '41')!r}"
    )
    assert "selftest: narrowed — the " in ran.out and (
        "django canaries of rule(s) 41 are judged inside the whole corpus's probe app" in ran.out
    ), ran.why("no line saying the Django forms were judged inside the whole corpus's probe app")
    refusals = [ln for ln in ran.out.splitlines() if any(r in ln for r in (*REFUSALS, "NameError"))]
    assert not refusals, ran.why(f"{len(refusals)} refusal line(s)")


def test_a_plant_refused_outside_the_narrowed_set_names_its_rule(shapes: ShapesWorld) -> None:
    """A batch plant refused for a rule outside the narrowed set is named as outside it."""
    rules = shapes.world.root / "quality" / "rules.yaml"
    saved = rules.read_bytes()
    form = "{ fixture: utils_module.py, plant_at: apps/zzz_canary/utils.py, mode: "
    text = saved.decode()
    if text.count(form + "create,") != 1:
        raise CouldNotLook("rule 11's utils_module.py form moved; the outside plant has no anchor")
    rules.write_text(text.replace(form + "create,", form + "replace,"))
    try:
        ran = shapes.narrowed("41")
    finally:
        rules.write_bytes(saved)
    refused = [ln for ln in ran.out.splitlines() if "PLANT REFUSED" in ln]
    assert refused, ran.why("the outside plant was not refused")
    assert all(
        ln.lstrip(" !").startswith("rule 11 (outside the narrowed set): ") for ln in refused
    ), ran.why(f"the refusal does not say it is outside the narrowed set: {refused}")


PRODUCT_FILES = {
    "frontend/src/app/page.tsx": 'import { redirect } from "next/navigation";\n\nimport { listOrganizations } from "@/api/client";\n\nexport default function RootPage(): never {\n    void listOrganizations;\n    redirect("/welcome");\n}\n',  # noqa: E501
    "frontend/src/tokens/theme.css": ":root {\n  --product-brand: #1d4ed8;\n}\n\nbody {\n  accent-color: var(--product-brand);\n}\n",  # noqa: E501
    "frontend/app/env.ts": 'export const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "";\n',
}
BARREL = {
    "frontend/src/components/index.ts": 'export * from "./deal-card";\nexport * from "./stage-badge";\nexport * from "./avatar";\n',  # noqa: E501
    "quality/local/rules.yaml": 'ratchets:\n  "52":\n    barrel: 3\n',
}
PARITY = "apps/accounts/tests/test_door_pair_parity.py"
PARITY_TEXT = '"""The consumer\'s (rest, mcp) parity test for accounts — the debt, paid."""\n\nDOOR_PAIR = ("rest", "mcp")\n\n\ndef test_the_pair_is_claimed() -> None:\n    assert DOOR_PAIR == ("rest", "mcp")\n'  # noqa: E501


@contextmanager
def remote_world(shapes: ShapesWorld) -> Iterator[str]:
    """The base declared by a `template` remote's synthetic tag, a product tree committed on it."""
    world = shapes.world
    upstream = world.root.parent / f"upstream-{secrets.token_hex(3)}"
    tag = f"v{shapes.version}"
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-hardlinks", str(world.root), str(upstream)],
        check=True,
        capture_output=True,
    )
    try:
        subprocess.run(
            ["git", "-C", str(upstream), "-c", "user.email=t@example.com", "-c", "user.name=T"]
            + ["tag", "-a", tag, "-m", "base", shapes.pre],
            check=True,
            capture_output=True,
        )
        world.git("remote", "add", "template", str(upstream))
        world.git("fetch", "-q", "template", f"refs/tags/{tag}:refs/tags/{tag}")
        planted = [p for p, _ in PRODUCT_FILES.items() if not (world.root / p).exists()]
        files = {p: PRODUCT_FILES[p] for p in planted}
        if not any((world.root / p).exists() for p in BARREL):
            files.update(BARREL)
        if not (world.root / PARITY).exists():
            files[PARITY] = PARITY_TEXT
            arch = world.root / "docs" / "product" / "architecture.md"
            arch.write_text(
                arch.read_text() + f"\ndivergence: {PARITY} — pays the (rest, mcp) debt\n"
            )
            world.git("add", "--", "docs/product/architecture.md")
        for rel, text in files.items():
            (world.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (world.root / rel).write_text(text)
            world.git("add", "-f", "--", rel)
        world.git("commit", "-q", "--allow-empty", "-m", "consumer: the product's own tree")
        yield f"{tag} (from the 'template' remote, derived from TEMPLATE_VERSION)"
    finally:
        shapes.reset()
        subprocess.run(
            ["git", "-C", str(world.root), "remote", "remove", "template"], capture_output=True
        )
        subprocess.run(["git", "-C", str(world.root), "tag", "-d", tag], capture_output=True)
        shutil.rmtree(upstream, ignore_errors=True)


def rule60_lowered(shapes: ShapesWorld, shape: str) -> str:
    """Rule 60's line on a declared base: the one form that needs the template's shape, lowered."""
    f = shapes.floors["60"]
    return (
        f"  rule 60 {f.name}: canaries {f.can}/{f.can} · negatives {f.neg - 1}/{f.neg - 1} — ok · "
        "0c/1n not producible on this shape (a_product_edit_with_no_base_declared.md needs the "
        f"template's own shape — no base declared — and this tree declares {shape}; recorded "
        f"{f.can}/{f.neg})"
    )


def common_asserts(shapes: ShapesWorld, ran: Ran, label: str, shape_line: str) -> None:
    """A narrowed run over 51 and 60: exit 0, its shape, its sentence, rule 51 whole, no refusal."""
    lines = ran.out.splitlines()
    assert ran.rc == 0, ran.why(f"{label}: the narrowed self-test did not exit 0")
    assert shape_line in lines, ran.why(f"{label}: no line {shape_line!r}")
    assert NARROWED in lines, ran.why(f"{label}: no narrowed-run sentence")
    assert shapes.floors["51"].ok_line("51") in lines, ran.why(f"{label}: rule 51 not whole")
    refusals = [ln for ln in lines if any(r in ln for r in REFUSALS)]
    assert not refusals, ran.why(f"{label}: {len(refusals)} refusal line(s)")
    assert "$(" not in ran.out, ran.why(f"{label}: the transcript carries a literal $(")


def test_the_remote_declared_base_is_green(shapes: ShapesWorld) -> None:
    """A base declared only by the `template` remote is green, rule 60 lowering its one form."""
    with remote_world(shapes) as shape:
        ran = shapes.whole() if WHOLE else shapes.narrowed()
    if WHOLE:
        judged = judge(shapes.floors, ran.out)
        assert ran.rc == 0, ran.why("W-C-remote: the whole self-test did not exit 0")
        assert "selftest: narrowed to rule(s)" not in ran.out, ran.why(
            "the whole run says narrowed"
        )
        assert not [row for row in judged if row[0] != "OK"], ran.why(f"rules not ok: {judged}")
        assert (
            "selftest clean: every canary fired, every negative stayed silent · "
            "1 form not producible on this shape." in ran.out.splitlines()
        ), ran.why(  # noqa: E501
            "no closing line counting the one lowered form"
        )
    else:
        common_asserts(shapes, ran, "W-C-remote", f"selftest: template base — {shape}")
    assert rule60_lowered(shapes, shape) in ran.out.splitlines(), ran.why(
        f"rule 60 is {rule_line(ran, '60')!r}"
    )
    assert "· 1 forms not producible on this shape (rules: 60)" in ran.out, ran.why(
        "the foot does not count one form not producible (rules: 60)"
    )


def test_the_file_declared_base_is_green_on_rules_51_and_60(shapes: ShapesWorld) -> None:
    """`scripts/local/template-base` declares the base and outranks the remote; still green."""
    with remote_world(shapes) as shape:
        base = shapes.world.root / "scripts" / "local" / "template-base"
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(shapes.pre + "\n")
        shapes.world.git("add", "-f", "--", "scripts/local/template-base")
        shapes.world.git("commit", "-q", "-m", "consumer: the declared base (W-C-file)")
        ran = shapes.narrowed()
    common_asserts(
        shapes,
        ran,
        "W-C-file",
        f"selftest: template base — {shapes.pre} (from scripts/local/template-base)",
    )
    assert rule60_lowered(shapes, shape) in ran.out.splitlines(), ran.why(
        f"rule 60 is {rule_line(ran, '60')!r}"
    )


HEAD = re.compile(r"canaries (\d+)/(\d+) · negatives (\d+)/(\d+) — ok")
CLAUSE = re.compile(
    r" · (\d+)c/(\d+)n not (?:in this world|producible on this shape) \(.*?recorded (\d+)/(\d+)\)"
)


def judge(floors: dict[str, Floor], transcript: str) -> list[tuple[str, str, str]]:
    """One (OK | BAD | CNL, rule id, why) row per planned rule, read off a run's rule lines."""
    lines = transcript.splitlines()
    rows = []
    for rid, f in floors.items():
        prefix = f"  rule {rid} {f.name}: "
        mine = [ln[len(prefix) :] for ln in lines if ln.startswith(prefix)]
        if len(mine) != 1:
            rows.append(("BAD", rid, f"the transcript carries {len(mine)} line(s) for it, want 1"))
            continue
        line = mine[0]
        if not f.on:
            rows.append(("OK" if line == "DISABLED — not planted" else "BAD", rid, line))
            continue
        m = HEAD.match(line)
        if not m:
            k = re.search(r" — (COULD NOT LOOK \(.*\))", line)
            rows.append(("CNL", rid, k.group(1)) if k else ("BAD", rid, f"not an ok line: {line}"))
            continue
        a, b, c, d = (int(x) for x in m.groups())
        if a != b or c != d:
            rows.append(("BAD", rid, f"judged {a}/{b} · {c}/{d}, not every form it expected"))
            continue
        rest, lc, lneg, why = line[m.end() :], 0, 0, ""
        while rest:
            k = CLAUSE.match(rest)
            if not k:
                why = f"an unreadable tail: {rest}"
                break
            if (int(k.group(3)), int(k.group(4))) != (f.can, f.neg):
                why = f"a clause records {k.group(3)}/{k.group(4)}, the plan {f.can}/{f.neg}"
                break
            lc, lneg, rest = lc + int(k.group(1)), lneg + int(k.group(2)), rest[k.end() :]
        if why:
            rows.append(("BAD", rid, why))
        elif b + lc != f.can or d + lneg != f.neg:
            rows.append(
                ("BAD", rid, f"{a}/{b} · {c}/{d} less {lc}c/{lneg}n is not {f.can}/{f.neg}")
            )
        else:
            rows.append(("OK", rid, f"{a}/{b} · {c}/{d}"))
    return rows


def verdict(rows: list[tuple[str, str, str]]) -> int:
    """0 every rule ok · 1 a judged rule failed · 2 nothing failed and a rule was not judged."""
    if any(v == "BAD" for v, _, _ in rows):
        return 1
    return 2 if any(v == "CNL" for v, _, _ in rows) else 0


def test_one_rule_that_could_not_look_is_named_could_not_look(shapes: ShapesWorld) -> None:
    """One rule that could not look inside a judged run is named so, and the verdict is 2."""
    floors = {rid: shapes.floors[rid] for rid in ("51", "60")}
    f51, f60 = floors["51"], floors["60"]
    transcript = (
        f51.ok_line("51")
        + f"\n  rule 60 {f60.name}: canaries 0/{f60.can} · negatives 0/{f60.neg} — COULD NOT LOOK "
        "(the probe's database would not open in this world)\n"
    )
    rows = judge(floors, transcript)
    assert (
        "CNL",
        "60",
        "COULD NOT LOOK (the probe's database would not open in this world)",
    ) in rows, rows
    assert [v for v, _, _ in rows].count("OK") == 1 and not [r for r in rows if r[0] == "BAD"], rows
    assert verdict(rows) == 2, rows
    assert not any("collides" in why for _, _, why in rows), rows


def _system_python() -> str | None:
    """A `python3` outside this venv that has `yaml` and no Django, or None."""
    venv = os.path.realpath(sys.prefix)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        found = shutil.which("python3", path=entry)
        if not found or os.path.realpath(entry).startswith(venv):
            continue
        probe = "import importlib.util as u, sys; sys.exit(0 if u.find_spec('yaml') and not u.find_spec('django') else 1)"  # noqa: E501
        if subprocess.run([found, "-I", "-c", probe], check=False).returncode == 0:
            return found
    return None


def _rules(argv: list[str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "DJANGO_"))}
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [*argv, "-m", "quality.gate", "--rules"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_rules_lists_on_a_bare_interpreter() -> None:
    """`--rules` on the system python, no venv, prints what the venv prints."""
    bare = _system_python()
    if bare is None:
        pytest.skip(
            "no system python3 outside the venv with `yaml` and without Django on this host"
        )
    venv = _rules([PY])
    assert venv.returncode == 0, venv.stderr
    done = _rules([bare])
    assert done.returncode == 0, f"{bare}: {done.stderr}"
    assert done.stdout == venv.stdout


BLOCKED = "import runpy, sys; sys.modules['django'] = None; sys.argv = ['quality.gate', '--rules']; runpy.run_module('quality.gate', run_name='__main__', alter_sys=True)"  # noqa: E501


def test_rules_lists_with_django_blocked() -> None:
    """The same listing with `django` blocked here, so a host with no bare python measures it."""
    venv = _rules([PY])
    done = _rules([PY, "-c", BLOCKED])
    assert done.returncode == 0, done.stderr
    assert done.stdout == venv.stdout
