"""The loop `pytest` leg: the shell's door flags, one slot, the collectors reconciled, the exits."""

# does-not-cover: a real pytest pass — every `test.sh` here is a planted script.

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from quality.djb import hold, scope
from quality.djb import registry as R
from quality.djb.legs import loop_pytest as lp
from quality.tests.fixtures import shell_gate

pytestmark = pytest.mark.drives("quality/djb/legs/loop_pytest.py", "scripts/test.sh")

ROOT = Path(__file__).resolve().parents[2]
GATE_TEXT = shell_gate.text()
TIER = GATE_TEXT.split("            TIER_ARGS=(--djb-tier=fast)\n", 1)[1].split(
    '            ./scripts/test.sh -n "$GATE_SLOT_WORKERS" "${TIER_ARGS[@]}"', 1
)[0]
#: A `test.sh` that writes `FAKE_COUNTS` identical counts files (or one odd), a refusal, an exit.
FAKE_TEST_SH = """#!/bin/sh
printf '%s\\n' "$*" >>"$FAKE_LOG"
dir=""
for a in "$@"; do case "$a" in --djb-scope-counts=*) dir=${a#--djb-scope-counts=} ;; esac; done
i=0
while [ -n "$dir" ] && [ "$i" -lt "${FAKE_COUNTS:-0}" ]; do
    printf 'workers=%s\\nselected: 7 of 9\\n' "${FAKE_WORKERS:-2}" >"$dir/gw$i"
    i=$((i + 1))
done
[ -z "${FAKE_ODD:-}" ] || printf 'workers=2\\nselected: 8 of 9\\n' >"$dir/gw-odd"
[ -z "${FAKE_REFUSE:-}" ] || printf '%s\\n' "$FAKE_REFUSE" >"$DJB_LOOP_REFUSAL_FILE"
exit "${FAKE_RC:-0}"
"""


def _scope(**kw: object) -> scope.Scope:
    found = scope.Scope()
    for k, v in kw.items():
        setattr(found, k, v)
    return found


SCOPES = {
    "full": _scope(mode="full"),
    "narrow": _scope(
        own=["example"],
        tests_only=["core"],
        changed_tests=["apps/core/tests/test_a.py"],
        seeded_tests=["apps/x/tests/test_b.py"],
        asked_impact=True,
        changed=["apps/example/models.py", "TEMPLATE_VERSION"],
        narrow=True,
        apps=["example", "events"],
    ),
    "impact": _scope(
        own=["example"],
        asked_impact=True,
        changed=["apps/example/models.py"],
        impact=scope.Impact(select="/tmp/djb-impact-select.planted"),  # noqa: S108 — a planted path the leg is handed, never opened
        narrow=True,
        apps=["example"],
    ),
    "fast-unnarrowed": _scope(own=["example", "core"], changed=["a.py"]),
}


def _shell_tier(found: scope.Scope, tmp: Path) -> list[str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(tmp),
        "LOOP_TIER_OWN_APPS": " ".join(found.own),
        "LOOP_SCOPE_TESTS_ONLY": " ".join(found.tests_only),
        "LOOP_SCOPE_CHANGED_TESTS": " ".join(found.changed_tests),
        "LOOP_SCOPE_SEEDED_TESTS": " ".join(found.seeded_tests),
        "LOOP_IMPACT": "1" if found.asked_impact else "",
        "LOOP_SCOPE_CHANGED_FILES": " ".join(found.changed),
        "LOOP_SCOPE_IMPACT_SELECT": found.impact.select,
        "LOOP_SCOPE_NARROW": "1" if found.narrow else "",
        "LOOP_SCOPE_APPS": " ".join(found.apps),
    }
    if found.mode == "full":
        return []
    script = f"TIER_ARGS=(--djb-tier=fast)\n{TIER}\nprintf '%s\\n' \"${{TIER_ARGS[@]}}\""
    done = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def test_the_registry_claims_the_loop_only_leg_last_of_the_three() -> None:
    table = R.load(ROOT)
    leg = table.leg("pytest")
    assert (leg.unit, set(leg.modes), leg.body) == (R.LOOP_ONLY, {"loop"}, lp.run)
    assert [g.name for g in table.mode_legs("loop")][-1] == "pytest"


@pytest.mark.parametrize("name", list(SCOPES))
def test_the_door_flags_are_the_shell_legs_for_one_planted_scope(name: str, scratch: Path) -> None:
    found = SCOPES[name]
    shell = _shell_tier(found, scratch)
    counts = [a for a in shell if a.startswith("--djb-scope-counts=")]
    mine = lp.tier_args(found)
    assert mine == [a for a in shell if a not in counts]
    assert lp.counted(mine) is bool(counts)


def test_the_canonical_scope_reads_back_field_by_field() -> None:
    text = "mode=fast own=example core scope=example events always=abc tests=- seeded=- "
    text += "alwayson=def map=-"
    fields = lp.canonical(text)
    assert fields["own"] == "example core" and fields["scope"] == "example events"
    assert fields["map"] == "-"


@pytest.fixture
def planted(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A planted `test.sh`, a slot of two workers that holds nothing, the leg's environment."""
    sh = scratch / "test.sh"
    sh.write_text(FAKE_TEST_SH)
    sh.chmod(0o755)
    monkeypatch.setattr(
        hold,
        "acquire_slot",
        lambda mode="loop", **kw: hold.Hold("slot", total=2, workers=2, phrase="planted"),
    )
    monkeypatch.setattr(hold, "nominal", lambda *a, **kw: (240, "typed", "planted"))
    return {
        "PATH": "/usr/bin:/bin",
        "FAKE_LOG": str(scratch / "calls.log"),
        "TEST_SH": str(sh),
        "TMPDIR": str(scratch),
    }


def _leg(env: dict[str, str], args: list[str], **fake: str) -> int:
    ctx = R.Ctx(ROOT, "loop", {**env, **fake})
    return lp.leg(ctx, args, test_sh=env["TEST_SH"])


NARROW = ["--djb-tier=fast", "--djb-scope=example", "--djb-scope-narrow"]


@pytest.mark.parametrize(
    ("args", "fake", "want", "said"),
    [
        (NARROW, {"FAKE_COUNTS": "2"}, 0, "reconciled across 2 collector file(s)"),
        (NARROW, {"FAKE_COUNTS": "1", "FAKE_ODD": "1"}, 2, "THE COLLECTORS DISAGREE"),
        (NARROW, {"FAKE_COUNTS": "1"}, 2, "1 of 2 collectors reported"),
        (NARROW, {"FAKE_COUNTS": "0"}, 2, "NO counts file to read"),
        (NARROW, {"FAKE_COUNTS": "2", "FAKE_REFUSE": "no scope"}, 2, "collection REFUSED"),
        (NARROW, {"FAKE_COUNTS": "2", "FAKE_RC": "1"}, 1, ""),
        (NARROW, {"FAKE_COUNTS": "2", "FAKE_RC": "5"}, 2, "DID NOT RUN THE SUITE (pytest exit 5)"),
        ([], {"FAKE_RC": "0"}, 0, ""),
        ([], {"FAKE_RC": "4"}, 2, "DID NOT RUN THE SUITE (pytest exit 4)"),
    ],
    ids=[
        "green",
        "disagree",
        "short",
        "no-counts",
        "refused",
        "red",
        "collected-nothing",
        "full-green",
        "usage",
    ],
)
def test_one_pass_in_one_slot_answers_as_the_shell_leg(
    planted: dict[str, str],
    capfd: pytest.CaptureFixture[str],
    args: list[str],
    fake: dict[str, str],
    want: int,
    said: str,
) -> None:
    assert _leg(planted, args, **fake) == want
    seen = capfd.readouterr()
    assert said in seen.out + seen.err
    call = Path(planted["FAKE_LOG"]).read_text().split()
    assert call[:2] == ["-n", "2"]
    assert any(a.startswith("--djb-scope-counts=") for a in call) is bool(args)


def test_a_docs_only_reuse_runs_no_pass_and_takes_no_slot(
    planted: dict[str, str], monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(hold, "acquire_slot", lambda *a, **kw: pytest.fail("a slot was taken"))
    assert _leg(planted, NARROW, GATE_LOOP_REUSE_TREE="abc123") == 0
    assert not Path(planted["FAKE_LOG"]).exists()
    assert "pytest: REUSED from the banked verdict on abc123" in capfd.readouterr().out


def test_the_impact_selection_file_is_removed_after_the_pass(
    planted: dict[str, str], scratch: Path
) -> None:
    select = scratch / "select"
    select.write_text("apps/x/tests/test_a.py\n")
    args = ["--djb-tier=fast", f"--djb-impact-select={select}"]
    assert _leg(planted, args, FAKE_COUNTS="2") == 0
    assert not select.exists()


def test_no_slot_is_could_not_look(
    planted: dict[str, str], monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    def refuse(*a: object, **kw: object) -> hold.Hold:
        raise hold.Refused("the slots are full")

    monkeypatch.setattr(hold, "acquire_slot", refuse)
    assert _leg(planted, NARROW) == 2
    assert "cause: the slots are full" in capfd.readouterr().err


def test_the_handed_down_flags_win_over_a_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(lp, "derive", lambda ctx: pytest.fail("derived a second scope"))
    monkeypatch.setattr(lp, "leg", lambda ctx, args, found=None: _record(seen, list(args), 0))
    env = {lp.ARGS: "--djb-tier=fast --djb-own-app=example"}
    assert lp.run(R.Ctx(ROOT, "loop", env)) == 0
    assert seen == [["--djb-tier=fast", "--djb-own-app=example"]]


def _product(root: Path) -> Path:
    (root / "apps").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "quality/local").mkdir(parents=True)
    (root / "quality/local/rules.yaml").write_text("rule_id_namespace: acme\n")
    return root


def test_a_product_trees_pass_runs_its_own_apps_by_path_and_says_so(
    planted: dict[str, str], scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    ctx = R.Ctx(_product(scratch / "tree"), "loop", planted)
    assert lp.leg(ctx, ["apps/bookings"], test_sh=planted["TEST_SH"]) == 0
    assert Path(planted["FAKE_LOG"]).read_text().split() == ["-n", "2", "apps/bookings"]
    line = (
        "  loop: a product tree — pytest runs the product's own apps: apps/bookings"
        " (the platform's are not a product's to pay for)"
    )
    assert line in capfd.readouterr().out.splitlines()


def test_a_product_with_no_app_yet_runs_no_pytest_and_says_so(
    planted: dict[str, str],
    scratch: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(hold, "acquire_slot", lambda *a, **kw: pytest.fail("a slot was taken"))
    ctx = R.Ctx(_product(scratch / "tree"), "loop", planted)
    assert lp.leg(ctx, [], test_sh=planted["TEST_SH"]) == 0
    assert not Path(planted["FAKE_LOG"]).exists()
    assert "  loop: a product tree with no app of its own yet — pytest runs nothing" in (
        capfd.readouterr().out
    )


def test_a_product_app_with_no_tests_yet_is_a_pass_never_could_not_look(
    planted: dict[str, str], scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    ctx = R.Ctx(_product(scratch / "tree"), "loop", {**planted, "FAKE_RC": "5"})
    assert lp.leg(ctx, ["apps/bookings"], test_sh=planted["TEST_SH"]) == 0
    out = capfd.readouterr().out.splitlines()
    assert "  loop: apps/bookings has no tests yet — nothing to run" in out


def test_the_template_names_no_product_app_through_the_partition() -> None:
    from quality import partition
    from quality.djb.legs import gate_tests

    named = tuple(p for p in partition.product_paths() if (ROOT / p / "apps.py").is_file())
    assert gate_tests.product_apps(ROOT) == named == ()


def _record(into: list[Any], item: Any, value: Any) -> Any:
    """Append `item` and answer `value`: a stand-in that notes it ran."""
    into.append(item)
    return value
