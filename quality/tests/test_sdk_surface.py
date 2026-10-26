"""`quality/sdk_surface.json`: derived byte-identical, the kit's names in it, the shim logs once."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from config.settings.base import template_version_shape
from quality.sdk import surface

pytestmark = pytest.mark.drives(
    "pilecap/*",
    "quality/sdk/*",
    "quality/sdk_surface.json",
    "frontend/src/kit/surface.json",
    "apps/core/*",
    "apps/*/services*",
    "apps/*/selectors.py",
    "apps/*/models.py",
    "config/settings/base.py",
)

ROOT = Path(__file__).resolve().parents[2]


def test_the_surface_regenerates_byte_identical() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "quality.sdk", "--surface", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "surface: current" in done.stdout


def test_the_surface_carries_the_kits_names() -> None:
    filed = json.loads((ROOT / surface.SURFACE).read_text())
    kit = json.loads((ROOT / surface.KIT_SURFACE).read_text())["modules"]
    assert filed["ts"] == kit
    assert kit, "the kit exports nothing — the ts block would be vacuous"


def test_every_model_base_carries_its_fields_and_meta() -> None:
    names = json.loads((ROOT / surface.SURFACE).read_text())["names"]
    base = names["pilecap.TenantScopedModel"]
    assert base["kind"] == "model" and base["migration"] is True
    assert "tenant" in dict(base["fields"]) and len(base["meta"]) == 12


def test_a_field_default_change_moves_the_digest() -> None:
    from django.db import models

    before = models.CharField(max_length=10, null=True).deconstruct()[1:]
    after = models.CharField(max_length=10, null=False).deconstruct()[1:]
    assert surface.digest(before) != surface.digest(after)


@pytest.mark.parametrize(
    ("old", "new", "narrowed"),
    [
        ("(*, a)", "(*, a, b=)", ""),
        ("(*, a)", "(*, a, b)", "required b added"),
        ("(*, a, b=)", "(*, a, b)", "b lost its default"),
        ("(*, a, b)", "(*, a)", "b removed"),
        ("(a, b)", "(a, *, b)", "positional b moved or removed"),
        ("(a, **kw)", "(a)", "**kwargs dropped"),
        ("(a, /, b)", "(x, /, b)", ""),
    ],
)
def test_narrowing_reads_a_required_parameter_and_not_an_optional_one(
    old: str, new: str, narrowed: str
) -> None:
    assert surface.narrowing(old, new) == narrowed


def test_signature_text_names_kinds_and_defaults_only() -> None:
    def f(a: int, /, b: str = "x", *, c: int, d: int = 1, **kw: object) -> None: ...

    assert surface.signature_text(f) == "(a, /, b=, *, c, d=, **kw)"


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        ({"since": "2.5.0", "until": "2.6.0", "instead": "f", "kind": "renamed"}, ""),
        ({"since": "2.5.0", "until": "2.5.1", "instead": "f", "kind": "renamed"}, "one minor"),
        ({"since": "2.5.0", "until": "2.6.0", "instead": "f", "kind": "gone"}, "none of"),
        ({"since": "2.5.0", "until": "2.6.0", "instead": "f", "kind": "signature"}, "old→new"),
        ({"since": "2.5.0", "until": "2.6.0", "instead": "g", "kind": "renamed"}, "itself"),
        ({"since": "2.5.0", "until": "2.6.0", "instead": "f", "kind": "removed"}, "`change`"),
        (
            {"since": "2.5.0", "until": "2.6.0", "instead": "f", "kind": "removed", "change": "x"},
            "",
        ),
    ],
)
def test_a_deprecation_is_a_promise_or_named(entry: dict[str, str], problem: str) -> None:
    found = surface.deprecation_problem("pilecap.old", entry, ["pilecap.old", "pilecap.g"])
    assert (problem in found) if problem else found == ""


SHIM_PROBE = """
import sys, types
import django
django.setup()
from structlog.testing import capture_logs
from pilecap import _deprecated
from pilecap._deprecated import Deprecation, shim
probe = types.ModuleType("pilecap.zz_shim_probe")
probe.new_name = lambda: "new"
table = {"old_name": Deprecation("2.5.0", "2.6.0", "new_name", "renamed")}
vars(probe)["__getattr__"] = shim(probe.__name__, table)
sys.modules[probe.__name__] = probe
with capture_logs() as logs:
    same = probe.old_name is probe.old_name is probe.new_name
try:
    probe.never_declared
    missing = "served"
except AttributeError:
    missing = "refused"
print(same, missing, [(e["event"], e["name"], e["until"], e["instead"]) for e in logs])
"""


def test_the_shim_serves_the_new_name_and_logs_once_per_process() -> None:
    done = subprocess.run(
        [sys.executable, "-c", SHIM_PROBE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
    )
    assert done.returncode == 0, done.stderr[-1500:]
    assert done.stdout.strip() == (
        "True refused [('pilecap.deprecated', 'pilecap.zz_shim_probe.old_name', '2.6.0',"
        " 'new_name')]"
    )


def test_a_pre_release_orders_below_its_release_and_above_the_last() -> None:
    ordered = ["2.4.1", "2.5.0a1", "2.5.0a2", "2.5.0b1", "2.5.0rc1", "2.5.0", "2.5.1", "2.6"]
    assert sorted(ordered, key=surface.version) == ordered
    assert len({surface.version(v) for v in ordered}) == len(ordered)


@pytest.mark.parametrize(
    ("typed", "canonical"),
    [("2.5.0-alpha.1", "2.5.0a1"), ("v2.5.0-beta.2", "2.5.0b2"), ("2.5.0-rc.1", "2.5.0rc1")],
)
def test_a_typed_pre_release_reads_as_its_canonical_form(typed: str, canonical: str) -> None:
    assert surface.version(typed) == surface.version(canonical)


@pytest.mark.parametrize("bad", ["2", "2.5.0.1", "2.5.0x1", "2.5.0a", "two.5.0", ""])
def test_a_version_that_does_not_parse_is_a_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        surface.version(bad)


@pytest.mark.parametrize(
    ("since", "until", "past"),
    [("2.5.0a1", "2.6.0", True), ("2.5.0", "2.6.0a1", True), ("2.5.0a1", "2.5.1", False)],
)
def test_a_pre_release_counts_as_its_release_for_the_minor(
    since: str, until: str, past: bool
) -> None:
    assert surface.one_minor_past(since, until) is past


@pytest.mark.parametrize("target", ["2.5.0a1", "2.5.0"])
def test_an_upgrade_to_the_kits_release_or_its_candidate_names_the_moved_screens(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], target: str
) -> None:
    from quality.sdk import upgrade

    def run(*argv: str) -> None:
        subprocess.run(["git", *argv], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "w@example.invalid")
    run("config", "user.name", "w")
    (tmp_path / "quality").mkdir()
    (tmp_path / surface.SURFACE).write_text(surface.render({"names": {}, "deprecations": {}}))
    (tmp_path / "frontend/src/app").mkdir(parents=True)
    (tmp_path / "frontend/src/app/page.tsx").write_text('import { x } from "@/screens/state";\n')
    for version in ("2.4.1", target):
        (tmp_path / "TEMPLATE_VERSION").write_text(f"{version}\n")
        run("add", "-A")
        run("commit", "-qm", version, "--allow-empty")
        run("branch", f"at-{version}")
    assert upgrade.sdk_step(tmp_path, "at-2.4.1", f"at-{target}") == 0
    assert (
        "imports @/screens/state: deprecated since 2.5.0, removed in 3.0; use @pilecap/ui/state"
        " — frontend/src/app/page.tsx:1"
    ) in capsys.readouterr().out


@pytest.mark.parametrize(
    ("text", "accepted"),
    [("2.5.0", True), ("2.5.0a2", True), ("2.5.0rc1", True), ("2.5.0.1", False), ("abc", False)],
)
def test_the_road_and_the_sdk_surface_read_one_grammar(text: str, accepted: bool) -> None:
    """`read_template_version`'s shape and `quality.sdk.surface.version` agree on these strings."""
    try:
        surface.version(text)
    except ValueError:
        by_surface = False
    else:
        by_surface = True
    assert (template_version_shape.fullmatch(text) is not None, by_surface) == (accepted, accepted)
