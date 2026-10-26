"""`docs/sdk/`: derived byte-identical, every export once, a missing contract line refused."""

from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.sdk import reference, surface

pytestmark = pytest.mark.drives(
    "pilecap/*",
    "quality/sdk/*",
    "quality/sdk_surface.json",
    "docs/sdk/*",
    "apps/core/*",
    "apps/core/scaffold/*",
    "apps/core/management/commands/scaffold.py",
    "apps/example_portal/*",
    "apps/usage/*",
    "apps/files/*",
    "apps/exports/*",
    "apps/events/*",
    "docs/product/build-contract.md",
    "quality/canary/*",
    "quality/engine/plants.py",
    ".claude/agents/builder.md",
    ".claude/skills/*",
)

ROOT = Path(__file__).resolve().parents[2]

#: The four definitions and the sentence each carries — the product builder's one path.
DEFINITIONS = {
    ".claude/agents/builder.md": (
        "first read `docs/sdk/reference.md`",
        "your territory is `apps/`, `frontend/`, their derived files",
        "`roads shape`",
        "`scaffold`",
        "`./scripts/feature.sh <app>`",
        "`./scripts/feature.sh <app> --drive <Noun>`",
        "`./scripts/take_release.sh`",
    ),
    ".claude/skills/platform-primer/SKILL.md": (
        "on a product the reference is the map; `django-conventions` is the template's builders'"
        " and is cited by the reference where a rule binds",
    ),
    ".claude/skills/product-manager/references/dispatch-briefs.md": (
        'a product builder\'s brief is territory + criteria pointer + "the one path"',
    ),
    ".claude/skills/rung-execution/SKILL.md": ("`./scripts/feature.sh <app>`",),
}


def test_the_reference_regenerates_byte_identical() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "quality.sdk", "--reference", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "reference: current" in done.stdout


def test_day_zero_is_the_same_page_in_an_exported_tree(tmp_path: Path) -> None:
    for top in ("apps", "frontend", "quality", "scripts", "README.md", "compose.yaml"):
        (tmp_path / top).symlink_to(ROOT / top)
    product = tmp_path / "docs" / "product"
    product.mkdir(parents=True)
    for page in (ROOT / "docs" / "product").glob("*.md"):
        shutil.copyfile(page, product / page.name)
    assert reference.day_zero_page(tmp_path) == reference.day_zero_page(ROOT)


def test_a_noun_a_plant_s_url_name_carries_is_on_the_hand_page() -> None:
    page = reference.hand_page(ROOT)
    reserved = page.split("refused for them:", 1)[1]
    assert "`cog`" in reserved and "`doodad`" in reserved, reserved


def test_every_export_is_in_the_reference_once() -> None:
    listed = reference.listed(ROOT)
    twice = sorted(name for name, n in Counter(listed).items() if n > 1)
    assert not twice, twice
    assert sorted(listed) == sorted(surface.read_facade(ROOT).names)


def test_every_discovered_file_the_page_lists_is_canonical_to_rule_11() -> None:
    """A file the discovered page tells a product to drop is never `djb.E011` on sight."""
    stems = {
        name.removesuffix(".py") for file, *_ in reference.DISCOVERED for name in file.split(" · ")
    }
    assert stems
    probe = "import django; django.setup(); from apps.core.checks import CANONICAL_MODULES as c; "
    probe += "print(' '.join(sorted(c)))"
    done = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
    )
    assert done.returncode == 0, done.stderr[-1500:]
    assert sorted(stems - set(done.stdout.split())) == []


def test_the_index_names_every_page() -> None:
    index = (ROOT / reference.INDEX).read_text()
    pages = sorted(p.name for p in (ROOT / reference.HOME).glob("*.md") if p.name != "reference.md")
    assert pages
    assert [p for p in pages if f"({p})" not in index] == []


def _world(tmp_path: Path, body: str) -> Path:
    (tmp_path / "pilecap").mkdir()
    (tmp_path / "quality").mkdir()
    (tmp_path / "pilecap/__init__.py").write_text(f'"""World."""\n\n__all__ = ["f"]\n\n{body}')
    doc = {"names": {"pilecap.f": {"kind": "function", "sig": "()"}}, "deprecations": {}, "ts": {}}
    (tmp_path / surface.SURFACE).write_text(surface.render(doc))
    return tmp_path


def test_an_export_with_no_contract_line_is_refused_naming_it(tmp_path: Path) -> None:
    world = _world(tmp_path, "\ndef f() -> None:\n    pass\n")
    out = io.StringIO()
    with redirect_stdout(out):
        rc = reference.main(["--root", str(world)])
    assert rc == 1, out.getvalue()
    assert "pilecap.f (pilecap/__init__.py:6) has no contract line" in out.getvalue()
    assert not (world / reference.HOME).exists()


def test_a_value_reads_its_contract_from_the_comment_above(tmp_path: Path) -> None:
    world = _world(tmp_path, "#: The one thing this world says.\nf = 'x'\n")
    entry = reference.entries(world)["pilecap"][0]
    assert (entry.name, entry.contract, entry.source) == (
        "pilecap.f",
        "The one thing this world says.",
        "pilecap/__init__.py:6",
    )


@pytest.mark.parametrize("path", sorted(DEFINITIONS))
def test_the_four_definitions_carry_the_one_path(path: str) -> None:
    text = " ".join((ROOT / path).read_text().split())
    assert [s for s in DEFINITIONS[path] if s not in text] == []


def test_the_one_path_drives_through_the_road_that_migrates_first() -> None:
    page = (ROOT / "docs/sdk/the-one-path.md").read_text()
    assert "6. `./scripts/feature.sh <app> --drive <Noun>` — " in page
    assert "`./scripts/drive_doors.sh <Noun>`" not in page


def test_the_one_path_names_the_roads_shape_command_newapp_prints_next() -> None:
    page = (ROOT / "docs/sdk/the-one-path.md").read_text()
    assert "`uv run python manage.py roads shape <shape> <app> <Noun>`" in page


def test_the_one_path_reaches_the_loop_on_a_laptop_and_the_refusal_points_at_it() -> None:
    from quality.djb import gate_args

    page = (ROOT / "docs/sdk/the-one-path.md").read_text()
    assert '`./scripts/feature.sh <app> --loop --here "<app>: <why>"`' in page
    assert "DJB_LOOP_HERE" not in page
    said = "\n".join(gate_args.OFF_BOX_SAID)
    assert "docs/sdk/the-one-path.md" in said
    assert '--loop --here "<rung-id>: <reason>"' in said


def test_the_hand_page_says_what_the_scaffold_writes_and_carries_what_its_refusals_cite() -> None:
    page = (ROOT / "docs/sdk/the-developers-hand.md").read_text()
    assert "needs `DJB_BASELINE_WRITE=1`" not in page
    assert "- **The noun's authz baseline** — `scaffold noun` writes" in page
    cited: list[str] = []
    for path in (
        "apps/core/scaffold/arms/_common.py",
        "apps/core/management/commands/newapp.py",
    ):
        text = (ROOT / path).read_text()
        assert "django-conventions" not in text, path
        cited += re.findall(r"docs/sdk/the-developers-hand\.md § ([^)`.]+)", text)
    assert cited and [c for c in cited if f"- **{c}** — " not in page] == [], cited


def test_the_shapes_page_carries_each_shapes_arguments_and_what_it_goes_on() -> None:
    from apps.core.scaffold.shapes import SHAPES

    page = (ROOT / "docs/sdk/shapes.md").read_text()
    lines = page.splitlines()
    for shape in SHAPES:
        mine = [ln for ln in lines if ln.split()[:1] == [shape.key]]
        assert mine and all(f" {shape.args} " in ln and f" on {shape.on} " in ln for ln in mine)


def test_the_surface_record_is_the_population() -> None:
    filed = json.loads((ROOT / surface.SURFACE).read_text())["names"]
    assert sorted(e.name for es in reference.entries(ROOT).values() for e in es) == sorted(filed)


#: The linking guide's sections, in order — the three forms, the lines, the record, the limits.
LINKING_SECTIONS = (
    "Which form",
    "A foreign key in three lines",
    "Reading and writing across it",
    "When the other noun archives or merges",
    "Where the decision is written",
    "What rule 7 refuses",
    "What the scaffold does not write",
    "The worked example",
)


def test_the_linking_guide_is_a_page_with_its_sections_in_order() -> None:
    assert ("linking-apps.md", "A link between two apps") in [
        (file, title) for file, title, _r in reference.EXTRA
    ]
    page = (ROOT / "docs/sdk/linking-apps.md").read_text()
    found = re.findall(r"^## (.+)$", page, re.M)
    assert found == list(LINKING_SECTIONS), found
    for said in ("on_delete=models.PROTECT", "makemigrations <your app>", "--merge", "divergence:"):
        assert said in page, said
    record = page.split("## Where the decision is written", 1)[1].split("\n## ", 1)[0]
    assert (
        "**The lead's two deliverables** — " in record
        and "(`docs/product/architecture.md`)" in record
    )
    assert "| core, accounts, <other app> |" in record and "**rejected:**" in record
    assert "contiguous comment block directly above it" in page


def test_the_linking_guide_names_the_scaffold_s_closed_field_types() -> None:
    kinds = reference.field_types(ROOT)
    assert "uuid" in kinds and "datetime" in kinds
    page = (ROOT / "docs/sdk/linking-apps.md").read_text()
    assert " ".join(f"`{k}`" for k in kinds) in page


def test_the_depends_on_row_and_the_child_and_field_shapes_point_at_the_linking_guide() -> None:
    discovered = (ROOT / "docs/sdk/discovered-files.md").read_text().splitlines()
    row = [ln for ln in discovered if ln.startswith("| `apps.py` |")]
    assert row and "(linking-apps.md)" in row[0], row
    shapes = (ROOT / "docs/sdk/shapes.md").read_text().splitlines()
    pointer = [ln for ln in shapes if "(linking-apps.md)" in ln]
    assert pointer and "`child`" in pointer[0] and "`field`" in pointer[0], pointer


#: The metering guide's sections, in order — declare, record, key, read, free, missing, example.
METERING_SECTIONS = (
    "The declaration",
    "Recording it",
    "The idempotency key",
    "Reading the numbers",
    "What comes free",
    "What is not there yet",
    "The worked example",
)


def test_the_metering_guide_is_a_page_with_its_sections_in_order() -> None:
    assert ("metering-usage.md", "Metering usage from a verb") in [
        (file, title) for file, title, _r in reference.EXTRA
    ]
    page = (ROOT / "docs/sdk/metering-usage.md").read_text()
    found = re.findall(r"^## (.+)$", page, re.M)
    assert found == list(METERING_SECTIONS), found
    for said in ("`<app>.<noun>.<unit>`", 'f"{job.pk}:{JOBS_CLOSED}"', "`GET /api/v1/meters/`"):
        assert said in page, said


def test_the_metering_guide_s_no_shape_line_holds_on_this_tree() -> None:
    from apps.core.scaffold.shapes import SHAPES

    assert [s.key for s in SHAPES if "meter" in s.key or "usage" in s.key] == []
    page = (ROOT / "docs/sdk/metering-usage.md").read_text()
    assert "- **No shape** — no `scaffold` shape writes `meters.py`" in page


def test_the_meters_row_points_at_the_metering_guide() -> None:
    discovered = (ROOT / "docs/sdk/discovered-files.md").read_text().splitlines()
    row = [ln for ln in discovered if ln.startswith("| `meters.py` |")]
    assert row and "(metering-usage.md)" in row[0], row


def test_a_docstring_s_first_paragraph_is_its_contract(tmp_path: Path) -> None:
    body = (
        '\ndef f() -> None:\n    """One sentence that wraps\n'
        '    onto a second line.\n\n    The body.\n    """\n'
    )
    entry = reference.entries(_world(tmp_path, body))["pilecap"][0]
    assert entry.contract == "One sentence that wraps onto a second line."


#: The sending guide's sections, in the order the page carries them.
SENDING = (
    "Inside your transaction",
    "The template",
    "The recipient",
    "Transactional or marketing",
    "What you get, and how to see it",
    "The limits",
)


def test_the_sending_guide_is_a_page_with_its_sections() -> None:
    assert "sending-messages.md" in {file for file, _t, _r in reference.EXTRA}
    page = reference.sending_page(ROOT)
    at = [page.find(f"\n## {heading}\n") for heading in SENDING]
    assert -1 not in at and at == sorted(at), at
    assert "`start_workflow_on_commit`" in page and "`apps/comms/services.py:" in page


def test_the_hand_page_points_a_verb_that_sends_at_the_guide() -> None:
    assert "[Sending a message](sending-messages.md)" in reference.hand_page(ROOT)


def test_a_value_s_comment_block_gives_its_first_paragraph(tmp_path: Path) -> None:
    world = _world(
        tmp_path, "#: One sentence that wraps\n#: onto a second line.\n#:\n#: More.\nf = 'x'\n"
    )
    entry = reference.entries(world)["pilecap"][0]
    assert entry.contract == "One sentence that wraps onto a second line."


#: The live-updates guide's sections, in the order the page carries them.
LIVE = (
    "Where the socket is",
    "How it authenticates",
    "What arrives",
    "Reconnecting",
    "The limits",
)


def test_the_live_updates_guide_is_a_page_with_its_sections() -> None:
    assert "live-updates.md" in {file for file, _t, _r in reference.EXTRA}
    page = reference.live_page(ROOT)
    at = [page.find(f"\n## {heading}\n") for heading in LIVE]
    assert -1 not in at and at == sorted(at), at
    assert "`frontend/next.config.ts:" in page and "`apps/realtime/consumers.py:" in page


DEPLOYING = "docs/sdk/deploying.md"
#: The developer's own order, one heading per ask.
DEPLOY_SPINE = [
    "## 1 · What the account owner runs once",
    "## 2 · The repository's variables",
    "## 3 · The deploy, and how to watch it",
    "## 4 · The first human and the first tenant",
    "## 5 · Each tenant's own setup",
    "## 6 · The smoke",
]


def _deploying() -> str:
    path = ROOT / DEPLOYING
    assert path.is_file(), f"{DEPLOYING} is not in the reference"
    return path.read_text()


def test_the_deploy_page_s_spine_is_the_developer_s_order() -> None:
    headings = [ln for ln in _deploying().splitlines() if ln.startswith("## ")]
    assert headings == DEPLOY_SPINE


def test_the_deploy_page_carries_the_bootstrap_and_every_variable_line_it_prints() -> None:
    page = _deploying()
    script = (ROOT / "deploy/iam/product_bootstrap.sh").read_text()
    printed = re.findall(r'echo "    gh variable set (\w+) ', script)
    assert printed, "product_bootstrap.sh prints no variable line"
    assert [v for v in printed if f"gh variable set {v} --repo <owner>/<repo>" not in page] == []
    assert "DJB_GITHUB_REPO=<owner>/<repo>" in page
    assert "./deploy/iam/product_bootstrap.sh --confirm" in page
    unset = page.split("## 3 ", 1)[0].split("## 2 ", 1)[1]
    assert "`AWS_DEPLOY_ROLE_ARN`" in unset and "`DJB_STAGE_TARGET`" in unset


def test_the_deploy_page_says_a_re_deploy_is_stage_sh_and_the_first_is_the_hand_walk() -> None:
    walk = _deploying().split("## 3 ", 1)[1].split("## 4 ", 1)[0]
    assert "./deploy/stage.sh <user>@<host> --env staging" in walk
    assert "`TREE`" in walk
    for part in range(8):
        assert f"(../runbooks/deploy.md#part-{part}--" in walk, part


def test_the_deploy_page_s_runbook_links_land_on_a_heading() -> None:
    runbook = (ROOT / "docs/runbooks/deploy.md").read_text().splitlines()
    anchors = {reference.slug(ln[3:]) for ln in runbook if ln.startswith("## ")}
    linked = re.findall(r"\(\.\./runbooks/deploy\.md#([\w-]+)\)", _deploying())
    assert linked and [a for a in linked if a not in anchors] == []


def test_the_deploy_page_puts_the_first_human_before_the_first_tenant() -> None:
    day_zero = _deploying().split("## 4 ", 1)[1].split("## 5 ", 1)[0]
    order = [
        day_zero.find(w)
        for w in ("zitadel_first_admin --email", "signs in", "bootstrap_tenant --email")
    ]
    assert -1 not in order and order == sorted(order), order


def test_the_deploy_page_links_the_tenant_setup_pages_rather_than_repeating_them() -> None:
    setup = _deploying().split("## 5 ", 1)[1].split("## 6 ", 1)[0]
    links = re.findall(r"\((pilecap[\w.]*\.md)#([\w-]+)\)", setup)
    assert {p for p, _a in links} >= {"pilecap.comms.md", "pilecap.connections.md"}
    for page, anchor in links:
        headings = (ROOT / "docs/sdk" / page).read_text().splitlines()
        assert anchor in {reference.slug(h[4:]) for h in headings if h.startswith("### ")}, anchor


def test_the_one_path_and_operating_it_link_the_deploy_page() -> None:
    for page in ("the-one-path.md", "operating.md"):
        assert "(deploying.md)" in (ROOT / "docs/sdk" / page).read_text(), page


#: What the shifted-citation world copies rather than links: the page folder and the cited file's.
SHIFTED = ("docs", "config")
#: Never linked into a scratch world: the checkout's own environment and its database pin.
UNLINKED = {".git", ".venv", ".rung", ".env"}


def _shifted_world(tmp_path: Path) -> Path:
    """This tree with `config/settings/discovery.py` one line longer and `docs/sdk/` as it is."""
    world = tmp_path / "shifted"
    world.mkdir()
    for top in ROOT.iterdir():
        if top.name in UNLINKED or top.name in SHIFTED:
            continue
        (world / top.name).symlink_to(top)
    shutil.copytree(ROOT / "config", world / "config")
    (world / "docs").mkdir()
    for part in (ROOT / "docs").iterdir():
        if part.name == "sdk":
            shutil.copytree(part, world / "docs" / "sdk")
        else:
            (world / "docs" / part.name).symlink_to(part)
    cited = world / "config/settings/discovery.py"
    cited.write_text("\n" + cited.read_text())
    return world


def test_the_leg_refuses_a_shifted_citation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from quality.djb import registry
    from quality.djb.legs import sdk_reference

    world = _shifted_world(tmp_path)
    assert sdk_reference.run(registry.Ctx(world, "fast", dict(os.environ))) == 1
    said = capsys.readouterr().err
    assert (
        "!! docs/sdk/discovered-files.md is stale — run: python -m quality.sdk --reference,"
        " then stage docs/sdk/"
    ) in said, said
    assert sdk_reference.run(registry.Ctx(ROOT, "fast", dict(os.environ))) == 0


def test_the_leg_runs_in_every_mode_right_after_ruff() -> None:
    from quality.djb import registry

    table = registry.load(ROOT)
    for mode in ("fast", "loop", "full"):
        names = [g.name for g in table.mode_legs(mode)]
        assert names[names.index("ruff") + 1] == "sdk-reference", (mode, names)


def _one_path() -> str:
    return (ROOT / "docs/sdk/the-one-path.md").read_text()


def _step(page: str, command: str) -> str:
    """The numbered line of `page` whose command is `command`."""
    return next(line for line in page.splitlines() if f". `{command}` — " in line)


def test_the_step_that_names_the_app_states_rule_32_with_a_worked_pair() -> None:
    step = _step(_one_path(), "uv run python manage.py newapp <app>")
    assert step.startswith("2. "), step
    for said in ("house rule 32", "`newapp workorders`", "`Job`", "never a noun's own plural"):
        assert said in step, (said, step)
    hand = (ROOT / "docs/sdk/the-developers-hand.md").read_text()
    labels = next(line for line in hand.splitlines() if line.startswith("- **App labels** — "))
    assert "never the noun's own plural" in labels and "house rule 32" in labels, labels


def test_the_face_is_the_step_after_the_drive_and_names_the_example_folder_the_templates() -> None:
    page = _one_path()
    drive = _step(page, "./scripts/feature.sh <app> --drive <Noun>")
    face = _step(page, "uv run python manage.py scaffold screen <Noun>")
    lines = page.splitlines()
    assert lines.index(face) == lines.index(drive) + 1
    assert "`frontend/src/app/example/`" in face and "worked example" in face, face


def _bound(rel: str, name: str) -> str:
    """`name`'s string in `rel`, by `ast`."""
    node = reference._node(ast.parse((ROOT / rel).read_text()), name)
    value = getattr(node, "value", None)
    assert isinstance(value, ast.Constant) and isinstance(value.value, str), (rel, name)
    return value.value


def _bound_keys(rel: str, name: str) -> set[str]:
    value = getattr(reference._node(ast.parse((ROOT / rel).read_text()), name), "value", None)
    assert isinstance(value, ast.Dict), (rel, name)
    keys = [k for k in value.keys if isinstance(k, ast.Name)]
    assert len(keys) == len(value.keys), (rel, name)
    return {_bound(rel, k.id) for k in keys}


def test_the_one_path_lists_every_file_scaffold_writes_outside_the_app() -> None:
    page = _one_path()
    block = page.split("## What `scaffold` writes outside `apps/<app>/`", 1)[1]
    for name, _said in reference.SCAFFOLD_WRITES:
        assert f"- `{_bound(reference.SCAFFOLD, name)}` — " in block, name


def test_an_unlisted_writer_is_could_not_look(tmp_path: Path) -> None:
    common = tmp_path / reference.SCAFFOLD
    common.parent.mkdir(parents=True)
    text = (ROOT / reference.SCAFFOLD).read_text()
    common.write_text(
        text + '\n\nLEDGER = "quality/ledger.yaml"\n\n\ndef f(root):\n    root / LEDGER\n'
    )
    with pytest.raises(CouldNotLook, match="root / LEDGER"):
        reference.scaffold_writes(tmp_path)


def _edited_world(tmp_path: Path, rel: str, old: str, new: str) -> Path:
    """This tree linked, with `rel` alone a copy carrying `new` for `old`."""
    world = tmp_path / "edited"
    world.mkdir()
    source, target = ROOT, world
    parts = Path(rel).parts
    for depth, part in enumerate(parts):
        for child in source.iterdir():
            if child.name != part and not (depth == 0 and child.name in UNLINKED):
                (target / child.name).symlink_to(child)
        source, target = source / part, target / part
        if depth < len(parts) - 1:
            target.mkdir()
    text = source.read_text()
    assert text.count(old) == 1, old
    target.write_text(text.replace(old, new))
    return world


def test_the_leg_reds_when_a_writer_s_path_moves_and_the_page_did_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from quality.djb import registry
    from quality.djb.legs import sdk_reference

    world = _edited_world(
        tmp_path,
        reference.SCAFFOLD,
        'BUDGETS = "quality/budgets.yaml"',
        'BUDGETS = "quality/budget_rows.yaml"',
    )
    assert sdk_reference.run(registry.Ctx(world, "fast", dict(os.environ))) == 1
    said = capsys.readouterr().err
    assert "!! docs/sdk/the-one-path.md is stale" in said, said


def test_day_zero_and_the_readme_state_the_cpu_and_the_compose_project_name() -> None:
    page = (ROOT / "docs/sdk/day-zero.md").read_text()
    assert f"**The CPU.** {reference.ARCHITECTURES} (`compose.yaml:" in page
    assert f"**The compose project name.** {reference.PROJECT_NAME} (`compose.yaml:" in page
    readme = " ".join((ROOT / "README.md").read_text().split())
    for said in ("one `linux/arm64` manifest", "amd64 laptop", "`djangobootstrap`", "platform-1"):
        assert said in readme, said


def test_the_hand_states_the_noun_s_owner_cascade_and_what_to_change() -> None:
    hand = (ROOT / "docs/sdk/the-developers-hand.md").read_text()
    owner = next(line for line in hand.splitlines() if line.startswith("- **The noun's owner** — "))
    for said in (
        "on_delete=CASCADE",
        "house rule 31",
        "PROTECT",
        "SET_NULL",
        "noun/models.py-tpl:",
    ):
        assert said in owner, (said, owner)


def test_the_face_step_says_where_a_product_page_lands_and_where_the_walk_lives() -> None:
    face = _step(_one_path(), "uv run python manage.py scaffold screen <Noun>")
    for said in (
        "`frontend/src/app/<page>/`",
        "`frontend/src/app/example/<page>/`",
        "`WALK_PREFIX` in `frontend/src/kit/routes.ts`",
        "`apps/core/scaffold/arms/screen.py:",
    ):
        assert said in face, (said, face)


def test_no_page_points_a_line_into_a_file_the_scaffold_grows() -> None:
    """A product's own `scaffold` moves those lines, and its next commit would find a page stale."""
    grown = _bound_keys("apps/core/scaffold/copier.py", "SHARED")
    grown.add(_bound("apps/core/scaffold/arms/screen.py", "LEXICON"))
    grown |= {_bound(reference.SCAFFOLD, name) for name, _said in reference.SCAFFOLD_WRITES}
    pointed = [
        f"{page.name}: {hit}"
        for page in sorted((ROOT / "docs/sdk").glob("*.md"))
        for hit in re.findall(r"`([^`\s]+):\d+`", page.read_text())
        if hit in grown
    ]
    assert pointed == [], pointed
