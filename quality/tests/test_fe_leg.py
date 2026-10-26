"""`fe_leg_run` (`scripts/fe_gate.sh`): absent, untouched, suspect and full, over scratch faces."""

# does-not-cover: whether pnpm's own frozen-lockfile detection is correct — only what it is handed.
# does-not-cover: a package-manager script wrapper's shape the goalpost census cannot see.
# does-not-cover: the live tree taking the full branch; every case is a fixture world.
# does-not-cover: what the face's typecheck, lint and test scripts check — only their status.

from __future__ import annotations

import importlib
import json
import re
import shlex
import shutil
import subprocess
import tarfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "frontend/",
    "frontend/openapi.json",
    "frontend/src/api/generated/schema.d.ts",
    "apps/example/models.py",
    "docs/product/queue.md",
    "scripts/fe_gate.sh",
    "scripts/goalpost_scan.py",
    "scripts/secrets_scan.sh",
)

ROOT = Path(__file__).resolve().parents[2]
ABSENT_PNPM = "/nonexistent/no-such-pnpm-binary"
COST = re.compile(
    r"fe leg cost: frozen-lockfile [0-9]+s \+ typecheck [0-9]+s \+ lint [0-9]+s \+ "
    r"test [0-9]+s \+ pin [0-9]+s = [0-9]+s"
)


@dataclass(frozen=True)
class Fe:
    """One `fe_leg_run`: its exit, the `FE_LEG_STATE` it left and its transcript."""

    rc: int
    state: str
    out: str


@pytest.fixture
def fe(scratch: Path, capture: Callable[..., Captured]) -> Callable[..., Fe]:
    """`fe(face, changed, mode=None, pnpm=None)`; an omitted mode is the one-argument contract."""
    count = 0

    def run(
        face: Path, changed: Sequence[str], mode: str | None = None, pnpm: str | None = None
    ) -> Fe:
        nonlocal count
        count += 1
        listing, sink = scratch / f"changed-{count}", scratch / f"fe-{count}.out"
        listing.write_bytes(b"".join(p.encode() + b"\0" for p in changed))
        call = f"fe_leg_run {str(listing)!r}" + ("" if mode is None else f" {mode!r}")
        script = (
            f". scripts/fe_gate.sh || exit 2\n{call} >{str(sink)!r} 2>&1\n"
            'echo "rc=$? state=${FE_LEG_STATE:-}"\n'
        )
        env = {"FE_FRONTEND_DIR": str(face)}
        if pnpm is not None:
            env["FE_PNPM"] = pnpm
        done = capture(["bash", "-c", script], cwd=ROOT, env=env)
        found = re.search(r"^rc=(\d+) state=(\S*)$", done.text(), re.MULTILINE)
        if done.rc != 0 or found is None:
            raise CouldNotLook(f"fe_leg_run did not report: {done.text()}")
        out = sink.read_text(errors="replace") if sink.is_file() else ""
        return Fe(int(found.group(1)), found.group(2), out)

    return run


@pytest.fixture
def clean_face(scratch: Path) -> Callable[[str], Path]:
    """`clean_face(name)`: a real pnpm project, one dependency, satisfied by its lockfile."""
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise CouldNotLook(
            "no pnpm on PATH — the full cases drive the real frozen-lockfile refusal"
        )

    def build(name: str) -> Path:
        face = scratch / name
        face.mkdir()
        _manifest(face, {"dependencies": {"left-pad": "1.3.0"}})
        done = subprocess.run(
            [pnpm, "install", "--lockfile-only", "--reporter=silent"],
            cwd=face,
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            raise CouldNotLook(f"pnpm install --lockfile-only failed: {done.stdout}{done.stderr}")
        return face

    return build


def _manifest(face: Path, extra: dict[str, object]) -> None:
    base = {"name": "fe-leg-fixture", "private": True, "version": "0.0.0"}
    (face / "package.json").write_text(json.dumps({**base, **extra}, indent=2))


def _scripts(face: Path, scripts: dict[str, str]) -> None:
    path = face / "package.json"
    data = json.loads(path.read_text())
    data["scripts"] = scripts
    path.write_text(json.dumps(data))


def _counter(stub_path: StubPath, marker: Path, name: str, rc: int = 0) -> str:
    return str(
        stub_path.plant(name, f'#!/usr/bin/env bash\necho "$*" >>{str(marker)!r}\nexit {rc}\n')
    )


def _calls(marker: Path) -> int:
    return len(marker.read_text().splitlines()) if marker.is_file() else 0


def test_absent(fe: Callable[..., Fe], scratch: Path) -> None:
    run = fe(scratch / "no-such-frontend", ["apps/example/models.py"])
    assert (run.rc, run.state) == (0, "absent") and "ABSENT" in run.out, run


def test_untouched_pnpm_never_invoked(
    fe: Callable[..., Fe], clean_face: Callable[[str], Path], stub_path: StubPath, scratch: Path
) -> None:
    face, marker = clean_face("fe-untouched"), scratch / "pnpm-was-called"
    tripwire = _counter(stub_path, marker, "pnpm-tripwire", rc=1)
    run = fe(face, ["apps/example/models.py", "docs/product/queue.md"], pnpm=tripwire)
    assert (run.rc, run.state) == (0, "untouched"), run
    assert not marker.exists(), "the toolchain tripwire fired"


def test_touched_toolchain_absent(fe: Callable[..., Fe], clean_face: Callable[[str], Path]) -> None:
    face = clean_face("fe-full")
    run = fe(face, [str(face / "package.json")], pnpm=ABSENT_PNPM)
    assert run.rc == 2, run


def test_full_no_manifest(fe: Callable[..., Fe], scratch: Path) -> None:
    face = scratch / "fe-no-manifest"
    face.mkdir()
    assert fe(face, [str(face / "anything")]).rc == 2


def test_full_no_lockfile(fe: Callable[..., Fe], scratch: Path) -> None:
    face = scratch / "fe-no-lock"
    face.mkdir()
    (face / "package.json").write_text('{"name":"x","private":true,"version":"0.0.0"}\n')
    assert fe(face, [str(face / "package.json")]).rc == 2


def test_frozen_lockfile_mismatch(fe: Callable[..., Fe], clean_face: Callable[[str], Path]) -> None:
    face = clean_face("fe-stale-lock")
    _manifest(face, {"dependencies": {"left-pad": "9.9.9"}})
    run = fe(face, [str(face / "package.json")])
    assert run.rc == 1, run
    assert "pnpm said: ERR_PNPM_OUTDATED_LOCKFILE" in run.out, run.out


FETCH_FAIL = (
    " ERR_PNPM_META_FETCH_FAIL  GET https://registry.npmjs.org/left-pad: request to "
    "https://registry.npmjs.org/left-pad failed, reason: getaddrinfo ENOTFOUND registry.npmjs.org"
)


def test_a_fetch_failure_is_could_not_look_with_pnpms_line_never_drift(
    fe: Callable[..., Fe], clean_face: Callable[[str], Path], stub_path: StubPath
) -> None:
    face = clean_face("fe-offline")
    offline = stub_path.plant(
        "pnpm-offline",
        f"#!/usr/bin/env bash\necho ' WARN  a config warning'\necho {FETCH_FAIL!r}\nexit 1\n",
    )
    run = fe(face, [str(face / "package.json")], pnpm=str(offline))
    assert run.rc == 2, run
    assert f"pnpm said: {FETCH_FAIL.strip()}" in run.out, run.out
    assert "no longer satisfies" not in run.out, run.out


CONFIG_MISMATCH = (
    " ERR_PNPM_LOCKFILE_CONFIG_MISMATCH  Cannot proceed with the frozen installation. "
    'The current "overrides" configuration doesn\'t match the value found in the lockfile'
)


def test_a_config_mismatch_is_drift_with_pnpms_line_never_could_not_look(
    fe: Callable[..., Fe], clean_face: Callable[[str], Path], stub_path: StubPath
) -> None:
    face = clean_face("fe-config-mismatch")
    mismatch = stub_path.plant(
        "pnpm-config-mismatch",
        "#!/usr/bin/env bash\necho ' WARN  a config warning'\n"
        f"echo {shlex.quote(CONFIG_MISMATCH)}\n"
        "echo 'Update your lockfile using \"pnpm install --no-frozen-lockfile\"'\nexit 1\n",
    )
    run = fe(face, [str(face / "package.json")], pnpm=str(mismatch))
    assert run.rc == 1, run
    assert f"pnpm said: {CONFIG_MISMATCH.strip()}" in run.out, run.out
    assert "will not fix it" not in run.out, run.out


def test_full_clean_no_test_script(
    fe: Callable[..., Fe], clean_face: Callable[[str], Path]
) -> None:
    face = clean_face("fe-clean-no-test")
    run = fe(face, [str(face / "package.json")])
    assert (run.rc, run.state) == (0, "full") and 'no "test" script declared' in run.out, run


def test_full_clean_test_passes(fe: Callable[..., Fe], clean_face: Callable[[str], Path]) -> None:
    face = clean_face("fe-clean-pass")
    _scripts(face, {"test": "exit 0"})
    run = fe(face, [str(face / "package.json")])
    assert (run.rc, run.state) == (0, "full"), run


def test_full_clean_test_fails(fe: Callable[..., Fe], clean_face: Callable[[str], Path]) -> None:
    face = clean_face("fe-clean-fail")
    _scripts(face, {"test": "exit 1"})
    assert fe(face, [str(face / "package.json")]).rc == 1


def test_a_planted_type_error_in_the_face_reds_the_leg(
    fe: Callable[..., Fe], scratch: Path
) -> None:
    archive = scratch / "face.tar"
    with archive.open("wb") as sink:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD", "frontend"],
            stdout=sink,
            stderr=subprocess.PIPE,
        )
    if done.returncode != 0:
        raise CouldNotLook(f"could not archive the committed face: {done.stderr.decode()}")
    with tarfile.open(archive) as tar:
        tar.extractall(scratch / "face", filter="data")
    copy = scratch / "face/frontend"
    state = copy / "src/kit/state.ts"
    if not state.is_file():
        raise CouldNotLook("no frontend/src/kit/state.ts on this tree — no face to plant in")
    (copy / "scripts/pin_client.sh").unlink(missing_ok=True)
    manifest = json.loads((copy / "package.json").read_text())
    _scripts(copy, {"typecheck": manifest["scripts"]["typecheck"]})
    control = fe(copy, [str(state)], "--loop")
    assert control.rc == 0, (
        f"the unplanted copy is not green, so the plant proves nothing: {control}"
    )
    with state.open("a") as handle:
        handle.write('\nexport const __fe_leg_planted_type_error: number = "not a number";\n')
    run = fe(copy, [str(state)], "--loop")
    assert run.rc == 1, run
    assert "RED: fe leg: the typecheck step failed" in run.out
    assert "src/kit/state.ts" in run.out


def test_a_suspect_client_is_decided_by_the_byte_pin(
    fe: Callable[..., Fe], stub_path: StubPath, scratch: Path
) -> None:
    face = scratch / "fe-suspect"
    (face / "scripts").mkdir(parents=True)
    pnpm = str(stub_path.plant("pnpm-present", "#!/usr/bin/env bash\nexit 0\n"))
    pin = face / "scripts/pin_client.sh"
    for want in (0, 1, 2):
        pin.write_text(f'#!/usr/bin/env bash\necho "planted pin exits {want}"\nexit {want}\n')
        pin.chmod(0o755)
        run = fe(face, ["apps/example/api.py"], "--loop", pnpm)
        assert (run.rc, run.state) == (want, "suspect"), run
        assert f"planted pin exits {want}" in run.out
    assert "offer: ./scripts/rung_tidy.sh --client" not in run.out, "2 is not drift"
    pin.unlink()
    run = fe(face, ["apps/example/api.py"], "--loop", pnpm)
    assert run.rc == 0 and "The byte pin was not run" in run.out, run
    assert "offer: ./scripts/rung_tidy.sh --client" in run.out


def test_under_a_unit_or_full_run_an_untouched_frontend_still_runs_the_leg(
    fe: Callable[..., Fe],
    clean_face: Callable[[str], Path],
    stub_path: StubPath,
    scratch: Path,
) -> None:
    face, marker = clean_face("fe-mode"), scratch / "pnpm-mode-marker"
    _scripts(face, {"test": "exit 0"})
    counter = _counter(stub_path, marker, "pnpm-counter")
    changed = ["apps/example/models.py", "docs/product/queue.md"]
    for mode in ("--leg", ""):
        marker.write_text("")
        run = fe(face, changed, mode, counter)
        assert (run.rc, run.state, _calls(marker)) == (0, "full", 2), (mode, run)
        assert "UNTOUCHED (fast path)" not in run.out, mode
        assert COST.search(run.out), (mode, run.out)
    for mode in ("--loop", "--fast"):
        marker.write_text("")
        run = fe(face, changed, mode, counter)
        assert (run.rc, run.state, _calls(marker)) == (0, "untouched", 0), (mode, run)
    assert fe(face, changed, "--leg", ABSENT_PNPM).rc == 2
    run = fe(scratch / "no-such-frontend-mode", changed, "")
    assert (run.rc, run.state) == (0, "absent"), run


def _boundary() -> ModuleType:
    """Rule 51's runner, imported from the tree."""
    return importlib.import_module("quality.runners.js_ingredient_boundary")


@pytest.mark.parametrize(
    ("rel", "line", "want"),
    [
        (
            "frontend/src/kit/zzz/up.tsx",
            'import { W } from "@/screens/welcome/welcome-screen";',
            ["upward-import"],
        ),
        (
            "frontend/src/screens/zzz/kit.tsx",
            'import { RefusalPanel } from "@pilecap/ui/refusal-panel";',
            [],
        ),
        (
            "frontend/src/screens/zzz/app.tsx",
            'import Page from "@/app/welcome/page";',
            ["upward-import"],
        ),
        (
            "frontend/src/kit/zzz/copy.tsx",
            'import { WIDGET_COPY } from "@pilecap/copy/widget";',
            [],
        ),
        (
            "frontend/src/primitives/zzz/up.tsx",
            'import { Card } from "@pilecap/ui/card";',
            ["upward-import"],
        ),
        (
            "frontend/src/screens/zzz/past.tsx",
            'import { AlertPanel } from "../../primitives/alert-panel";',
            ["past-the-kit"],
        ),
        (
            "frontend/src/screens/zzz/past.tsx",
            'import { DealCard } from "@/components/deal-card";',
            ["past-the-kit"],
        ),
        (
            "frontend/src/screens/zzz/past.tsx",
            'import "@/tokens/tokens.css";',
            ["past-the-kit"],
        ),
        (
            "frontend/src/screens/zzz/door.tsx",
            'import { AlertPanel } from "@pilecap/ui/alert-panel";',
            [],
        ),
        (
            "frontend/src/kit/zzz/below.tsx",
            'import { AlertPanel } from "../../primitives/alert-panel";',
            [],
        ),
    ],
)
def test_rule_51_ranks_the_kit_and_resolves_the_package_aliases(
    scratch: Path, rel: str, line: str, want: list[str]
) -> None:
    path = scratch / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{line}\n")
    found, checked = _boundary().findings_in(path, Path(rel))
    assert checked == 1, f"{rel}: the import was not resolved onto the chain"
    assert [each["klass"] for each in found] == want, found


def test_every_package_alias_the_face_spells_resolves_onto_the_chain() -> None:
    runner = _boundary()
    seen: list[str] = []
    for path in sorted((ROOT / "frontend/src").rglob("*.ts*")):
        rel = path.relative_to(ROOT)
        for lineno, spec, _ in runner.imports_in(path, rel):
            if spec.startswith("@pilecap/"):
                seen.append(spec)
                target = runner.resolve_spec(spec, rel)
                assert target is not None and runner.layer_of(target), f"{rel}:{lineno} {spec}"
    assert seen, "the face spells no @pilecap/ import — the census is looking at nothing"
