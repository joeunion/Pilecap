"""The verifier image's machinery: the reaper, the seams, the policy, the bootstrap, the recipe.

does-not-cover: whether `who` on Amazon Linux lists a Session Manager session as the shim does.
does-not-cover: whether `shutdown -h now` on a one-time Spot instance terminates, not stops.
does-not-cover: whether IAM reads the policy the way these text assertions do.
does-not-cover: whether the AWS error codes the shims answer are the codes the real API returns.
does-not-cover: the image itself — nothing here bakes, boots or logs into anything.
does-not-cover: the bake seam as a running thing; its runcmd order and ownership are read as text.
does-not-cover: whether systemd parses the reaper's unit and timer; both are read as text.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.deploy_scaffold import DeployScaffold
from quality.tests.fixtures.fake_clock import plant_clock
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "deploy/verifier/**",
    "scripts/verifier_box.sh",
    "deploy/iam/**",
    "deploy/policy_summary.py",
    "deploy/tests/**",
    "docs/runbooks/deploy.md",
    "frontend/package.json",
    "scripts/check.sh",
)

ROOT = Path(__file__).resolve().parents[2]
REAPER = "deploy/verifier/idle_reaper.sh"
SEAM = "deploy/verifier/user-data.yaml.in"
BAKE_SEAM = "deploy/verifier/bake-user-data.yaml"
UNIT = "deploy/verifier/verifier-reaper.service"
TIMER = "deploy/verifier/verifier-reaper.timer"
BAKE = "deploy/verifier/bake.sh"
POLICY = "deploy/iam/verifier-ops-policy.json"
TRUST = "deploy/iam/verifier-box-trust.json"
BOOTSTRAP = "deploy/iam/verifier_bootstrap.sh"
SUMMARY = "deploy/policy_summary.py"
SUBJECTS = (REAPER, SEAM, BAKE_SEAM, UNIT, TIMER, BAKE, POLICY, TRUST, BOOTSTRAP, SUMMARY)
CHECKOUT_PY = ROOT / ".venv" / "bin" / "python"
BASE_PATH = "/usr/bin:/bin"


@pytest.fixture(scope="module", autouse=True)
def subjects() -> None:
    """Every subject present, the checkout's interpreter and a bash on PATH; else could-not-look."""
    for subject in SUBJECTS:
        if not (ROOT / subject).is_file():
            raise CouldNotLook(f"{subject} missing — there is nothing to drive")
    if not os.access(CHECKOUT_PY, os.X_OK):
        raise CouldNotLook(
            "this checkout has no .venv/bin/python, and the python files this module runs are"
            " written at the version that venv holds. Run ./scripts/setup.sh first"
        )
    if shutil.which("bash") is None or not Path("/usr/bin/python3").exists():
        raise CouldNotLook("no bash on PATH or no /usr/bin/python3 — the shims need both")


def read(relative: str) -> str:
    """A tracked file's text, by its path from the checkout root."""
    return (ROOT / relative).read_text()


def run(
    argv: Sequence[str], env: Mapping[str, str], cwd: Path = ROOT, stdin: Path | None = None
) -> tuple[int, str]:
    """`argv` under exactly `env` (the drive's `env -i`), both streams to a file; exit and text."""
    with open(stdin or os.devnull, "rb") as source, tempfile.TemporaryFile() as sink:
        done = subprocess.run(
            list(argv), env=dict(env), cwd=cwd, stdin=source, stdout=sink, stderr=subprocess.STDOUT
        )
        sink.seek(0)
        return done.returncode, sink.read().decode(errors="replace")


def stubs_at(directory: Path, scripts: Mapping[str, str]) -> StubPath:
    """A fresh stub directory at `directory` with each named shim planted through `StubPath`."""
    directory.mkdir(parents=True)
    stubs = StubPath(directory)
    for name, body in scripts.items():
        stubs.plant(name, body)
    return stubs


def recorder(tool: str) -> str:
    """A shim that appends `<tool> <argv>` to `$REC/ran` and succeeds."""
    return f'#!/usr/bin/env bash\nprintf \'%s\\n\' "{tool} $*" >>"$REC/ran"\nexit 0\n'


def line_no(text: str, pattern: str, last: bool = False) -> int | None:
    """The 1-based number of the first (or last) line of `text` matching `pattern`, or None."""
    found = [n for n, line in enumerate(text.splitlines(), 1) if re.search(pattern, line)]
    if not found:
        return None
    return found[-1] if last else found[0]


def count_lines(text: str, pattern: str) -> int:
    """How many lines of `text` match `pattern` — `grep -cE`."""
    return sum(1 for line in text.splitlines() if re.search(pattern, line))


def iso_at(epoch: int) -> str:
    """`epoch` in the ISO-8601 UTC spelling the tags and /etc/verifier/expires use."""
    stamp = datetime.datetime.fromtimestamp(epoch, datetime.UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


# the reaper

REAPER_SHIMS = {
    "who": r"""#!/usr/bin/env bash
printf '%s' "$*" >>"$REC/who.argv"
printf '\n' >>"$REC/who.argv"
cat "$REC/who"
""",
    "pgrep": r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$REC/pgrep.argv"
pat=""
for a in "$@"; do pat="$a"; done
if grep -E -- "$pat" "$REC/procs" >/dev/null 2>&1; then
    echo 4242
    exit 0
fi
exit 1
""",
    "shutdown": r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$REC/shutdown.argv"
exit 0
""",
    "logger": r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$REC/logger.argv"
exit 0
""",
}
SESSION = "verifier pts/0        2026-09-15 21:04 (10.0.0.9)"


@dataclass
class ReaperBox:
    """A fake machine root the reaper reads through `VERIFIER_ROOT`, its clock a file."""

    root: Path
    stubs: StubPath

    @property
    def rec(self) -> Path:
        """Where the shims record and the case plants their answers."""
        return self.root / "rec"

    @property
    def now(self) -> int:
        """The epoch `date +%s` answers."""
        return int((self.rec / "now").read_text())

    def put(self, relative: str, value: str) -> None:
        """Write `value` and a newline at `relative` under the root."""
        (self.root / relative).write_text(f"{value}\n")

    def expires_in(self, seconds: int) -> str:
        """Write /etc/verifier/expires at now + `seconds`; the ISO spelling written."""
        when = iso_at(self.now + seconds)
        self.put("etc/verifier/expires", when)
        return when

    def active_minutes_ago(self, minutes: int) -> None:
        """Touch the activity marker and set its mtime `minutes` before now."""
        marker = self.root / "run/verifier/last-activity"
        marker.write_text("")
        stamp = float(self.now - minutes * 60)
        os.utime(marker, (stamp, stamp))

    def booted_seconds_ago(self, seconds: int) -> None:
        """Write /run/verifier/boot-at `seconds` before now."""
        self.put("run/verifier/boot-at", str(self.now - seconds))

    def reap(self) -> tuple[int, str]:
        """Run the reaper once under the drive's `env -i` world."""
        env = {
            "PATH": self.stubs.path,
            "HOME": str(self.root),
            "REC": str(self.rec),
            "VERIFIER_ROOT": str(self.root),
            "VERIFIER_USER": "verifier",
        }
        return run(["bash", str(ROOT / REAPER)], env)

    def log(self) -> str:
        """The reaper's own log, empty when it wrote none."""
        path = self.root / "var/log/verifier-reaper.log"
        return path.read_text() if path.is_file() else ""

    def shutdowns(self) -> int:
        """How many times `shutdown` was called."""
        path = self.rec / "shutdown.argv"
        return count_lines(path.read_text(), ".") if path.is_file() else 0


@pytest.fixture
def box(scratch: Path, stub_path: StubPath) -> ReaperBox:
    """A fresh fake machine: the four directories, the shims, the clock, no session or process."""
    root = scratch / "box"
    for sub in ("etc/verifier", "run/verifier", "var/log", "rec"):
        (root / sub).mkdir(parents=True)
    for name, body in REAPER_SHIMS.items():
        stub_path.plant(name, body)
    plant_clock(stub_path, root / "rec/now", int(time.time()))
    made = ReaperBox(root, stub_path)
    (made.rec / "who").write_text("")
    (made.rec / "procs").write_text("")
    return made


def assert_decision(made: ReaperBox, rc: int, out: str, want: str, shutdowns: int) -> None:
    """The decision on stdout and in the log, in the log's shape, with exactly `shutdowns` calls."""
    report = f"--- reaper stdout ---\n{out}\n--- reaper log ---\n{made.log()}"
    assert rc == 0, f"the reaper exited {rc}\n{report}"
    assert want in out, f"wanted the decision '{want}' on stdout\n{report}"
    assert want in made.log(), (
        f"the decision '{want}' was not appended to var/log/verifier-reaper.log\n{report}"
    )
    assert "reaper " in made.log(), (
        f"the log line does not carry the 'reaper <utc> <decision>' shape\n{report}"
    )
    assert made.shutdowns() == shutdowns, (
        f"wanted {shutdowns} shutdown call(s), got {made.shutdowns()}\n{report}"
    )


def assert_could_not_look(made: ReaperBox, rc: int, out: str, want: str) -> None:
    """Exit 2, `want` said, and no shutdown — the timer asks again in a minute."""
    assert rc == 2, f"wanted exit 2 (could-not-look), got {rc}\n{out}"
    assert want in out, f"wanted '{want}' on stderr\n{out}"
    assert made.shutdowns() == 0, (
        f"it could not decide and shut the box down anyway ({made.shutdowns()} call(s))"
    )


def test_reaper_holds_on_a_fresh_boot(box: ReaperBox) -> None:
    """Activity a minute ago under a 30-minute threshold holds."""
    box.expires_in(4 * 3600)
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(1)
    assert_decision(box, *box.reap(), "hold: fresh (1m < 30m)", 0)


def test_reaper_holds_while_a_session_is_live(box: ReaperBox) -> None:
    """A logged-in session holds an idle box."""
    box.expires_in(4 * 3600)
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(90)
    box.put("rec/who", SESSION)
    assert_decision(box, *box.reap(), "hold: session", 0)


def test_reaper_holds_while_the_gate_is_running(box: ReaperBox) -> None:
    """A running gate holds an idle box."""
    box.expires_in(4 * 3600)
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(90)
    box.put("rec/procs", "bash ./scripts/check.sh --loop")
    assert_decision(box, *box.reap(), "hold: busy (check.sh)", 0)


def test_reaper_reaps_when_idle_passes_the_threshold(box: ReaperBox) -> None:
    """31 idle minutes over 30 reaps, names the command, and calls it with `-h now`."""
    box.expires_in(4 * 3600)
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(31)
    rc, out = box.reap()
    assert_decision(box, rc, out, "reap: idle 31m ≥ 30m", 1)
    assert "shutdown -h now" in out, "the reap decision does not name 'shutdown -h now'"
    called = (box.rec / "shutdown.argv").read_text()
    assert "-h now" in called, f"shutdown was not called with '-h now': {called}"


def test_reaper_reaps_an_expired_box_even_mid_gate(box: ReaperBox) -> None:
    """Past expiry reaps through a live session and a running gate."""
    when = box.expires_in(-1)
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(0)
    box.put("rec/who", SESSION)
    box.put("rec/procs", "bash ./scripts/check.sh --loop")
    box.booted_seconds_ago(7200)
    assert_decision(box, *box.reap(), f"reap: expired {when}", 1)


def test_reaper_reaps_when_expires_is_unreadable(box: ReaperBox) -> None:
    """No expiry file fails closed."""
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(1)
    box.booted_seconds_ago(7200)
    assert_decision(box, *box.reap(), "reap: expires unreadable — fail closed", 1)


def test_reaper_reaps_when_expires_is_unparsable(box: ReaperBox) -> None:
    """An expiry that is not a date fails closed."""
    box.put("etc/verifier/expires", "not-a-date")
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(1)
    box.booted_seconds_ago(7200)
    assert_decision(box, *box.reap(), "reap: expires unreadable — fail closed", 1)


def test_reaper_uses_the_default_idle_minutes_and_says_so(box: ReaperBox) -> None:
    """No idle-minutes file means 30, and the decision says it was the default."""
    box.expires_in(4 * 3600)
    box.active_minutes_ago(31)
    assert_decision(box, *box.reap(), "reap: idle 31m ≥ 30m (default)", 1)


def test_reaper_reaps_when_the_activity_marker_is_missing(box: ReaperBox) -> None:
    """No activity marker fails closed, reached only after the session and busy holds."""
    box.expires_in(4 * 3600)
    box.put("etc/verifier/idle-minutes", "30")
    assert_decision(box, *box.reap(), "reap: last-activity missing — fail closed", 1)


def test_reaper_cannot_read_the_clock_and_says_so(box: ReaperBox) -> None:
    """A clock that answers no epoch is could-not-look, never a decision."""
    box.expires_in(4 * 3600)
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(1)
    box.put("rec/now", "not-an-epoch")
    assert_could_not_look(box, *box.reap(), "could not read the clock")


def test_reaper_cannot_read_the_activity_mtime_and_says_so(box: ReaperBox) -> None:
    """A marker `stat` cannot answer for is could-not-look, in either dialect."""
    box.expires_in(4 * 3600)
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(1)
    failing = '#!/usr/bin/env bash\necho "stat: cannot read file system information" >&2\nexit 1\n'
    box.stubs.plant("stat", failing)
    assert_could_not_look(box, *box.reap(), "could not read the mtime")


def test_reaper_holds_inside_the_boot_grace(box: ReaperBox) -> None:
    """A box 30 s from boot holds past an expiry its unsynced clock may have misread."""
    box.expires_in(-1)
    box.put("etc/verifier/idle-minutes", "30")
    box.active_minutes_ago(0)
    box.booted_seconds_ago(30)
    assert_decision(box, *box.reap(), "hold: boot grace", 0)


# the user-data seams

SEAM_PUBKEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheDriveOnly"  # pragma: allowlist secret
    " verifier@drive"
)
SEAM_OWNER = "a-session-name"
SEAM_EXPIRES = "2026-09-16T03:10:00Z"
SEAM_IDLE = "30"
SEAM_IMAGE = "ami-0drive0drive0drive"
SLOT = r"\$\{[A-Z_]+\}"
ANY_SLOT = r"\$\{[A-Za-z_]+\}"


def render_seam() -> str:
    """The launch seam with its five slots filled, as the wrapper's `sed` fills them."""
    text = read(SEAM)
    for slot, value in (
        ("VERIFIER_PUBKEY", SEAM_PUBKEY),
        ("VERIFIER_OWNER", SEAM_OWNER),
        ("VERIFIER_EXPIRES", SEAM_EXPIRES),
        ("VERIFIER_IDLE_MINUTES", SEAM_IDLE),
        ("VERIFIER_IMAGE_ID", SEAM_IMAGE),
    ):
        text = text.replace("${" + slot + "}", value)
    return text


def bake_user() -> str:
    """The bake account, read off the recipe's `BAKE_USER` knob."""
    found = re.search(r'^BAKE_USER="\$\{DJB_VERIFIER_BAKE_USER:-(.*)\}"$', read(BAKE), re.M)
    return found.group(1) if found else ""


def bake_checkout() -> str:
    """The checkout path, read off the recipe's `BAKE_CHECKOUT` knob with the user substituted."""
    found = re.search(r'^BAKE_CHECKOUT="\$\{DJB_VERIFIER_CHECKOUT:-(.*)\}"$', read(BAKE), re.M)
    return found.group(1).replace("${BAKE_USER}", bake_user()) if found else ""


def render_bake_seam() -> str:
    """The bake seam with its two slots filled from the recipe's own knobs."""
    text = read(BAKE_SEAM).replace("${VERIFIER_PUBKEY}", SEAM_PUBKEY)
    return text.replace("${VERIFIER_CHECKOUT}", bake_checkout())


def runcmd_lines(doc: dict[str, Any]) -> list[str]:
    """Each runcmd entry as one string, a list entry joined on spaces."""
    entries = doc.get("runcmd") or []
    return [" ".join(str(x) for x in e) if isinstance(e, list) else str(e) for e in entries]


def test_user_data_renders_with_four_values_and_leaves_no_slot() -> None:
    """Exactly the five slots the wrapper renders, none left after, and valid YAML."""
    slots = sorted(set(re.findall(SLOT, read(SEAM))))
    want = [
        "${VERIFIER_EXPIRES}",
        "${VERIFIER_IDLE_MINUTES}",
        "${VERIFIER_IMAGE_ID}",
        "${VERIFIER_OWNER}",
        "${VERIFIER_PUBKEY}",
    ]
    assert slots == want, (
        f"the template's slots are '{' '.join(slots)}' — the wrapper renders exactly five"
    )
    rendered = render_seam()
    left = re.findall(ANY_SLOT, rendered)
    assert not left, f"a slot survived the render: {' '.join(left)}"
    assert isinstance(yaml.safe_load(rendered), dict), "the rendered cloud-config is not valid YAML"


def test_user_data_carries_the_four_properties_the_launch_depends_on() -> None:
    """The key, the three /etc/verifier files, the timer, and the unit beside them."""
    doc = yaml.safe_load(render_seam())
    problems = []
    users = {u.get("name"): u for u in doc.get("users", []) if isinstance(u, dict)}
    verifier = users.get("verifier")
    if verifier is None:
        problems.append("no user named verifier")
    elif SEAM_PUBKEY not in [str(k).strip() for k in verifier.get("ssh_authorized_keys", [])]:
        problems.append("the public key is not in users[verifier].ssh_authorized_keys")
    files = {f.get("path"): f for f in doc.get("write_files", []) if isinstance(f, dict)}
    for path, want in (
        ("/etc/verifier/expires", SEAM_EXPIRES),
        ("/etc/verifier/owner", SEAM_OWNER),
        ("/etc/verifier/idle-minutes", SEAM_IDLE),
    ):
        written = files.get(path)
        if written is None:
            problems.append(f"{path} is not written")
        elif str(written.get("content", "")).strip() != want:
            got = str(written.get("content", "")).strip()
            problems.append(f"{path} carries {got!r}, wanted {want!r}")
    if "verifier-reaper.timer" not in " ".join(str(x) for x in doc.get("runcmd", [])):
        problems.append("runcmd does not enable verifier-reaper.timer")
    assert not problems, "; ".join(problems)
    assert Path(REAPER).name in read(UNIT), f"the service unit does not name {Path(REAPER).name}"
    assert re.search(r"OnUnitActiveSec=|OnBootSec=", read(TIMER)), (
        "the timer declares no OnBootSec/OnUnitActiveSec"
    )


def test_bake_user_data_installs_git_and_initialises_the_checkout() -> None:
    """Git installed, then the checkout made on main with updateInstead, for the bake user."""
    slots = sorted(set(re.findall(SLOT, read(BAKE_SEAM))))
    assert slots == ["${VERIFIER_CHECKOUT}", "${VERIFIER_PUBKEY}"], (
        f"the bake seam's slots are '{' '.join(slots)}' — the wrapper renders"
        " ${VERIFIER_CHECKOUT} and ${VERIFIER_PUBKEY}"
    )
    rendered = render_bake_seam()
    left = re.findall(ANY_SLOT, rendered)
    assert not left, f"a slot survived the render: {' '.join(left)}"
    checkout, user = bake_checkout(), bake_user()
    assert checkout and user, (
        f"could not read BAKE_USER/BAKE_CHECKOUT out of {BAKE} — this case needs both"
    )
    lines = runcmd_lines(yaml.safe_load(rendered))
    problems = []
    if not lines:
        problems.append("runcmd is empty")
    installs = [
        i for i, x in enumerate(lines) if re.search(r"\b(dnf|yum)\b", x) and " install" in x
    ]
    if not installs:
        problems.append("no package install in runcmd")
    elif not any(re.search(r"\bgit\b", lines[i]) for i in installs):
        problems.append(f"the package install does not name git: {[lines[i] for i in installs]!r}")
    init = [
        i for i, x in enumerate(lines) if re.search(r"\bgit\b", x) and re.search(r"\binit\b", x)
    ]
    if not init:
        problems.append("no runcmd initialises a git repository")
    else:
        first = lines[init[0]]
        if checkout not in first:
            problems.append(f"the init does not name the recipe's checkout {checkout}: {first!r}")
        if not re.search(r"-b\s+main\b", first):
            problems.append(f"the init does not put HEAD on main (-b main): {first!r}")
        if installs and init[0] < min(installs):
            problems.append("the repository is initialised before git is installed")
        deny = [
            x
            for x in lines
            if "receive.denyCurrentBranch" in x and "updateInstead" in x and checkout in x
        ]
        if not deny:
            problems.append(
                f"no runcmd sets receive.denyCurrentBranch=updateInstead on {checkout} — "
                "`push --force main:main` into a checked-out branch is refused by git"
            )
    if not [x for x in lines if user in x and checkout in x]:
        problems.append(f"no runcmd gives {checkout} to the bake user {user}")
    assert not problems, "; ".join(problems)
    assert checkout not in read(BAKE_SEAM), (
        f"the bake seam spells {checkout} literally — it must carry the ${{VERIFIER_CHECKOUT}} slot"
    )


def test_bake_user_data_writes_its_ready_marker_last() -> None:
    """The last runcmd tests every setting the seam made, then writes a marker under /run."""
    checkout = bake_checkout()
    lines = runcmd_lines(yaml.safe_load(render_bake_seam()))
    assert lines, "runcmd is empty"
    last = lines[-1]
    found = re.search(r"(/\S*ready\S*)", last)
    assert found is not None, f"the last runcmd writes no ready marker: {last!r}"
    path = found.group(1)
    problems = []
    if not path.startswith("/run/"):
        problems.append(
            f"the ready marker {path} is not under /run — anything else is captured into the image"
        )
    earlier = [x for x in lines[:-1] if path in x and not x.startswith("install ")]
    if earlier:
        problems.append(f"the marker is also touched before the last entry: {earlier!r}")
    if not (re.search(r"\btest\b", last) and checkout in last):
        problems.append(
            f"the last runcmd writes the marker without testing {checkout} first: {last!r}"
        )
    sets: dict[str, str] = {}
    for line in lines[:-1]:
        for key, value in re.findall(r"\bconfig\s+(\S+)\s+(\S+)", line):
            sets[key] = value
    for key, value in sorted(sets.items()):
        if key not in last or value not in last:
            problems.append(
                f"runcmd sets {key}={value} and the marker guard does not assert it: {last!r}"
            )
    for key in sorted(re.findall(r"\b([a-z]+\.[a-zA-Z]+)\b", last)):
        if key not in sets:
            problems.append(f"the marker guard asserts {key}, which no runcmd of this seam sets")
    assert not problems, "; ".join(problems)


# the ops policy


def statements(relative: str = POLICY) -> list[dict[str, Any]]:
    """The policy document's statements."""
    return list(json.loads(read(relative))["Statement"])


def listed(value: Any) -> list[Any]:
    """`value` as a list, a scalar wrapped."""
    return value if isinstance(value, list) else [value]


def test_policy_summary_prints_every_statement(scratch: Path) -> None:
    """`policy_summary.py role` on stdin prints one line per statement and flags no S3 delete."""
    rc, out = run([str(CHECKOUT_PY), SUMMARY, "role"], dict(os.environ), stdin=ROOT / POLICY)
    assert rc == 0, f"policy_summary.py exited {rc}: {out}"
    want, got = len(statements()), count_lines(out, ".")
    assert want == got, f"{want} statement(s) in the document but {got} line(s) in the summary"
    assert "CAN DELETE" not in out, (
        "the summary flags an S3 delete grant — this policy has no s3: action at all"
    )


def test_policy_every_terminate_allow_is_tag_conditioned() -> None:
    """Every TerminateInstances Allow is conditioned on `djb:role`, and one exists."""
    problems, seen = [], 0
    for s in statements():
        if s["Effect"] != "Allow" or "ec2:TerminateInstances" not in listed(s["Action"]):
            continue
        seen += 1
        if "ec2:ResourceTag/djb:role" not in json.dumps(s.get("Condition", {})):
            problems.append(f"{s.get('Sid')} has no ec2:ResourceTag/djb:role condition")
    if seen == 0:
        problems.append(
            "no TerminateInstances Allow at all — the wrapper could not take a box down"
        )
    assert not problems, "; ".join(problems)


def test_policy_run_instances_on_an_instance_needs_all_three_request_tags() -> None:
    """RunInstances on instance/* requires role, owner and expires at request time."""
    problems, seen = [], 0
    for s in statements():
        res = listed(s["Resource"])
        if s["Effect"] != "Allow" or "ec2:RunInstances" not in listed(s["Action"]):
            continue
        if not any(r.endswith(":instance/*") for r in res):
            continue
        seen += 1
        cond = json.dumps(s.get("Condition", {}))
        for key in (
            "aws:RequestTag/djb:role",
            "aws:RequestTag/djb:owner",
            "aws:RequestTag/djb:expires",
        ):
            if key not in cond:
                problems.append(f"{s.get('Sid')} does not require {key}")
        if "instance/*" in json.dumps(res) and len(res) > 1:
            problems.append(
                f"{s.get('Sid')} mixes instance/* with other resources under one Condition"
            )
    if seen == 0:
        problems.append("no RunInstances Allow on instance/* at all")
    assert not problems, "; ".join(problems)


def test_policy_tags_the_image_and_the_snapshot_a_capture_creates() -> None:
    """The create-time CreateTags reaches instances AND the account-less image and snapshot ARNs."""
    problems, seen = [], 0
    for s in statements():
        if s["Effect"] != "Allow" or "ec2:CreateTags" not in listed(s["Action"]):
            continue
        cond = json.dumps(s.get("Condition", {}))
        if "ec2:CreateAction" not in cond:
            continue
        seen += 1
        res = listed(s["Resource"])
        if "CreateImage" not in cond:
            problems.append(f"{s.get('Sid')} does not allow tagging during CreateImage")
        for want in (
            "arn:aws:ec2:${REGION}:${ACCOUNT_ID}:*/*",
            "arn:aws:ec2:${REGION}::image/*",
            "arn:aws:ec2:${REGION}::snapshot/*",
        ):
            if want not in res:
                problems.append(f"{s.get('Sid')} does not reach {want}")
    if seen == 0:
        problems.append(
            "no ec2:CreateTags Allow at all — nothing this credential creates could be tagged"
        )
    assert not problems, "; ".join(problems)


def test_policy_lets_a_claim_retag_a_pooled_box_and_nothing_more() -> None:
    """Exactly one re-tag grant: `djb:for` alone, on this namespace's pooled verifier instances."""
    problems: list[str] = []
    retag = []
    for s in statements():
        acts = listed(s["Action"])
        if s["Effect"] != "Allow" or "ec2:CreateTags" not in acts:
            continue
        cond = s.get("Condition", {})
        if "ec2:CreateAction" in json.dumps(cond):
            continue
        sid = s.get("Sid")
        retag.append(sid)
        if acts != ["ec2:CreateTags"]:
            problems.append(f"{sid} grants {acts!r} beside CreateTags")
        res = listed(s["Resource"])
        if res != ["arn:aws:ec2:${REGION}:${ACCOUNT_ID}:instance/*"]:
            problems.append(f"{sid} reaches {res!r} — wanted this account's instances only")
        equals = cond.get("StringEquals", {})
        for key, want in (
            ("ec2:ResourceTag/djb:role", "verifier"),
            ("ec2:ResourceTag/djb:namespace", "${NAMESPACE}"),
            ("ec2:ResourceTag/djb:for", "pool"),
        ):
            if equals.get(key) != want:
                problems.append(f"{sid}: {key} is {equals.get(key)!r}, wanted {want!r}")
        keys = cond.get("ForAllValues:StringEquals", {}).get("aws:TagKeys")
        if keys not in (["djb:for"], "djb:for"):
            problems.append(
                f"{sid}: aws:TagKeys is {keys!r}, wanted exactly ['djb:for'] under ForAllValues"
            )
        if set(cond) - {"StringEquals", "ForAllValues:StringEquals"}:
            problems.append(f"{sid} carries condition operators {sorted(cond)!r}")
    if not retag:
        problems.append(
            "no CreateTags Allow outside ec2:CreateAction — a claim's djb:for re-tag is refused"
            " and the pool over-counts"
        )
    elif len(retag) > 1:
        problems.append(
            f"{len(retag)} CreateTags Allows outside ec2:CreateAction"
            f" ({', '.join(map(str, retag))}) — wanted exactly the one re-tag"
        )
    assert not problems, "; ".join(problems)


def test_policy_passrole_names_only_the_verifier_box_role() -> None:
    """PassRole names exactly `${NAMESPACE}-verifier-box`, pinned to a service."""
    problems, roles = [], []
    for s in statements():
        if "iam:PassRole" not in listed(s["Action"]):
            continue
        roles.extend(listed(s["Resource"]))
        if "iam:PassedToService" not in json.dumps(s.get("Condition", {})):
            problems.append(f"{s.get('Sid')} passes a role without pinning iam:PassedToService")
    if len(roles) != 1 or not roles[0].endswith("-verifier-box"):
        problems.append(f"PassRole names {roles!r} — it must name exactly the verifier box role")
    elif "${NAMESPACE}" not in roles[0]:
        problems.append(
            f"PassRole names a FIXED role {roles[0]!r} — it must derive from the"
            " deployment namespace"
        )
    assert not problems, "; ".join(problems)


def test_policy_is_scoped_to_one_deployment_namespace() -> None:
    """Every tag-bearing grant of the seven scoped actions carries a `djb:namespace` condition."""
    must_be_scoped = {
        "ec2:RunInstances": "aws:RequestTag/djb:namespace",
        "ec2:TerminateInstances": "ec2:ResourceTag/djb:namespace",
        "ec2:CreateImage": "ec2:ResourceTag/djb:namespace",
        "ec2:DeregisterImage": "ec2:ResourceTag/djb:namespace",
        "ec2:DeleteSnapshot": "ec2:ResourceTag/djb:namespace",
        "ssm:StartSession": "ssm:resourceTag/djb:namespace",
        "ec2:GetConsoleOutput": "ec2:ResourceTag/djb:namespace",
    }
    problems, scoped = [], 0
    for s in statements():
        if s["Effect"] != "Allow":
            continue
        res = listed(s["Resource"])
        kinds = ("instance/*", "image/*", "snapshot/*", "security-group/*")
        if not any(kind in r for r in res for kind in kinds):
            continue
        if all(r.startswith("arn:aws:ec2:${REGION}::") for r in res):
            continue
        for action in listed(s["Action"]):
            key = must_be_scoped.get(action)
            if key is None:
                continue
            if "djb:namespace" not in json.dumps(s.get("Condition", {})):
                problems.append(
                    f"{s.get('Sid')} grants {action} with no djb:namespace condition (wanted {key})"
                )
            else:
                scoped += 1
    if scoped == 0:
        problems.append("no statement is namespace-scoped at all")
    assert not problems, "; ".join(problems)


def tree_hits(pattern: str, *directories: str) -> list[str]:
    """`grep -rInE` over `directories`: `path:line:text` for each matching line of a text file."""
    hits = []
    for directory in directories:
        for path in sorted((ROOT / directory).rglob("*")):
            data = path.read_bytes() if path.is_file() else b""
            if not data or b"\0" in data:
                continue
            for n, line in enumerate(data.decode(errors="replace").splitlines(), 1):
                if re.search(pattern, line):
                    hits.append(f"{path.relative_to(ROOT)}:{n}:{line}")
    return hits


def test_no_product_name_is_baked_into_the_machinery() -> None:
    """No product slug, account id or region literal; the names composed from the namespace."""
    slug = "pile" + "cap"
    hits = tree_hits(f"{slug}[-/]", "deploy/verifier", "deploy/iam")
    assert not hits, "a deployment slug is hard-coded:\n" + "\n".join(hits)
    accounts = tree_hits(r"[^0-9][0-9]{12}[^0-9]", "deploy/verifier", "deploy/iam")
    assert not accounts, "an AWS account id is hard-coded:\n" + "\n".join(accounts)
    regions = tree_hits(
        r"\b(us|eu|ap|ca|sa|me|af|il)-(gov-)?"
        r"(east|west|north|south|central|northeast|northwest|southeast|southwest)-[0-9]\b",
        "deploy/verifier",
        "deploy/iam",
    )
    assert not regions, "a region is hard-coded:\n" + "\n".join(regions)
    composed = ("DJB_DEPLOY_NAMESPACE" in read(BOOTSTRAP)) + (
        "${NAMESPACE}-verifier-box" in read(POLICY)
    )
    assert composed == 2, (
        f"the names are absent but not composed ({composed}/2) — an empty slot is not a derivation"
    )


def test_policy_denies_every_write_to_an_environment_box() -> None:
    """A Deny covers the four writes on any Project-tagged instance with no `djb:role`."""
    problems: list[str] = []
    found = None
    for s in statements():
        if s["Effect"] != "Deny":
            continue
        found = s
        acts = listed(s["Action"])
        for want in (
            "ec2:TerminateInstances",
            "ec2:StopInstances",
            "ec2:RebootInstances",
            "ec2:ModifyInstanceAttribute",
        ):
            if want not in acts:
                problems.append(f"the Deny does not cover {want}")
        null = s.get("Condition", {}).get("Null", {})
        if str(null.get("ec2:ResourceTag/Project", "")).lower() != "false":
            problems.append("the Deny does not require a Project tag to be PRESENT")
        if str(null.get("ec2:ResourceTag/djb:role", "")).lower() != "true":
            problems.append("the Deny does not require djb:role to be ABSENT")
    if found is None:
        problems.append("there is no Deny statement at all")
    assert not problems, "; ".join(problems)


def test_policy_grants_none_of_the_forbidden_action_families() -> None:
    """No iam write, secrets, s3, ecr, security-group or launch-template write, no wildcard."""
    forbidden = [
        r"^iam:(Create|Put|Attach|Delete)",
        r"^secretsmanager:",
        r"^s3:",
        r"^ecr:",
        r"^ec2:(Authorize|Create)SecurityGroup",
        r"^ec2:CreateLaunchTemplate",
    ]
    problems = []
    for s in statements():
        if s["Effect"] != "Allow":
            continue
        for action in listed(s["Action"]):
            problems += [
                f"{s.get('Sid')} grants {action}" for f in forbidden if re.match(f, action)
            ]
            if action == "*" or action.endswith(":*"):
                problems.append(f"{s.get('Sid')} grants the wildcard {action}")
    assert not problems, "; ".join(problems)


def test_the_box_role_trusts_ec2_and_nothing_else() -> None:
    """One Allow statement: `sts:AssumeRole` by `ec2.amazonaws.com` alone."""
    sts = json.loads(read(TRUST)).get("Statement", [])
    problems = []
    if len(sts) != 1:
        problems.append(
            f"the trust policy has {len(sts)} statements — one principal, one statement"
        )
    for s in sts:
        if s.get("Effect") != "Allow":
            problems.append("the trust statement is not an Allow")
        principal = s.get("Principal", {})
        if principal != {"Service": "ec2.amazonaws.com"}:
            problems.append(f"the principal is {principal!r}, not the EC2 service alone")
        if listed(s.get("Action")) != ["sts:AssumeRole"]:
            problems.append(
                f"the trust action is {listed(s.get('Action'))!r}, not sts:AssumeRole alone"
            )
    assert not problems, "; ".join(problems)


# the owner's bootstrap

AWS_SHIM = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$REC/aws.argv"
MODE="$(cat "$REC/mode")"
while [ "$#" -gt 0 ]; do
    case "$1" in
    --region | --profile) shift 2 ;;
    *) break ;;
    esac
done
printf '%s %s\n' "${1:-}" "${2:-}" >>"$REC/aws.ops"
case "$1 $2" in
"sts get-caller-identity")
    printf '%s\n' "$(cat "$REC/account")"
    ;;
"iam get-policy" | "iam get-user" | "iam get-instance-profile")
    if [ "$MODE" = "exists" ]; then
        case "$*" in
        *DefaultVersionId*) cat "$REC/policy.version" 2>/dev/null || echo "v1" ;;
        *) echo '{"ok":true}' ;;
        esac
    else
        echo "An error occurred (NoSuchEntity) when calling the operation" >&2
        exit 254
    fi
    ;;
"iam get-policy-version")
    if [ "$MODE" = "exists" ]; then
        cat "$REC/policy.live" 2>/dev/null || echo "{}"
    else
        echo "An error occurred (NoSuchEntity) when calling the operation" >&2
        exit 254
    fi
    ;;
"iam get-role-policy")
    if [ -f "$REC/rolepolicy.live" ]; then
        cat "$REC/rolepolicy.live"
    else
        echo "An error occurred (NoSuchEntity) when calling the GetRolePolicy operation" >&2
        exit 254
    fi
    ;;
"iam get-role")
    _slr="$(cat "$REC/spot-slr" 2>/dev/null || true)"
    case "$* $_slr" in
    *AWSServiceRoleForEC2Spot*exists*) echo '{"ok":true}' ;;
    *AWSServiceRoleForEC2Spot*absent*)
        echo "An error occurred (NoSuchEntity) when calling the GetRole operation" >&2
        exit 254
        ;;
    esac
    if [ "$MODE" = "exists" ]; then
        echo '{"ok":true}'
    else
        echo "An error occurred (NoSuchEntity) when calling the operation" >&2
        exit 254
    fi
    ;;
"iam list-access-keys")
    if [ "$MODE" = "exists" ]; then
        echo "FAKE-EXISTING-KEY-ID"
    fi
    ;;
"ec2 describe-security-groups")
    if [ "$MODE" = "exists" ]; then
        echo "sg-0verifier"
    else
        echo "None"
    fi
    ;;
"ec2 describe-vpcs")
    echo "vpc-0default"
    ;;
"iam create-access-key")
    _s="driveOnly""NotARealSecret0000000000000000"
    printf '{"AccessKey":{"AccessKeyId":"FAKE-DRIVE-KEY-ID","SecretAccessKey":"%s"}}\n' "$_s"
    ;;
"ec2 create-security-group")
    echo "sg-0verifier"
    ;;
*)
    echo "{}"
    ;;
esac
exit 0
"""
NAMESPACE = "drivens"
ACCOUNT = "050254549871"
REGION = "us-east-1"
CREATES = r"(create|attach|add-role|authorize)-"


@dataclass
class Account:
    """A recording `aws` answering from files the case writes: account, mode, live documents."""

    root: Path
    stubs: StubPath

    @property
    def rec(self) -> Path:
        """Where `aws` records and reads its answers."""
        return self.root / "rec"

    def answer(self, name: str, value: str) -> None:
        """Plant one answer file under `rec/`."""
        (self.rec / name).write_text(f"{value}\n" if not value.endswith("\n") else value)

    def env(self, *, drop: Sequence[str] = (), **extra: str) -> dict[str, str]:
        """The drive's `env -i` world with all three coordinates, less `drop`, plus `extra`."""
        world = {
            "PATH": f"{self.stubs.bin}:{BASE_PATH}",
            "HOME": str(self.root),
            "REC": str(self.rec),
            "DJB_DEPLOY_NAMESPACE": NAMESPACE,
            "DJB_VERIFIER_ACCOUNT": ACCOUNT,
            "DJB_VERIFIER_REGION": REGION,
            **extra,
        }
        return {k: v for k, v in world.items() if k not in drop}

    def bootstrap(self, *args: str, script: Path = ROOT / BOOTSTRAP, **env: Any) -> tuple[int, str]:
        """Run the bootstrap once under this account's world."""
        return run(["bash", str(script), *args], self.env(**env))

    def text(self, name: str) -> str:
        """A record's text, empty when nothing was recorded."""
        path = self.rec / name
        return path.read_text() if path.is_file() else ""

    def calls(self, pattern: str) -> int:
        """How many `<service> <operation>` records match `pattern`."""
        return count_lines(self.text("aws.ops"), pattern)


def open_account(root: Path) -> Account:
    """A fresh account at `root`: the recording `aws`, the pinned id, nothing existing yet."""
    (root / "rec").mkdir(parents=True)
    made = Account(root, stubs_at(root / "bin", {"aws": AWS_SHIM}))
    made.answer("account", ACCOUNT)
    made.answer("mode", "fresh")
    return made


@pytest.fixture
def account(scratch: Path) -> Account:
    """A fresh account under this test's scratch."""
    return open_account(scratch / "account")


def report(made: Account, out: str) -> str:
    """The bootstrap's output and the recorded argv, for a failure message."""
    argv = made.text("aws.argv") or "(no aws call recorded)"
    return f"--- bootstrap stdout ---\n{out}\n--- aws argv ---\n{argv}"


def rendered_policy() -> str:
    """The tracked policy with its three slots filled — a copy, never the script's own render."""
    text = read(POLICY)
    for slot, value in (("ACCOUNT_ID", ACCOUNT), ("REGION", REGION), ("NAMESPACE", NAMESPACE)):
        text = text.replace("${" + slot + "}", value)
    return text


def rendered_ecr_policy() -> dict[str, Any]:
    """The box role's registry grant as the bootstrap must render it, composed here."""
    repo = f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{NAMESPACE}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
            {
                "Effect": "Allow",
                "Action": [
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                    "ecr:PutImage",
                    "ecr:DescribeImages",
                    "ecr:ListImages",
                ],
                "Resource": [f"{repo}/djb-web", f"{repo}/djb-worker"],
            },
        ],
    }


def test_bootstrap_refuses_without_a_deployment_namespace(account: Account) -> None:
    """No namespace is exit 2 naming the variable, with not one aws call, even under --confirm."""
    rc, out = account.bootstrap(
        "--confirm", drop=("DJB_DEPLOY_NAMESPACE", "DJB_VERIFIER_ACCOUNT", "DJB_VERIFIER_REGION")
    )
    assert rc == 2, f"wanted exit 2 with no namespace, got {rc}\n{report(account, out)}"
    assert "DJB_DEPLOY_NAMESPACE" in out, "the refusal does not name DJB_DEPLOY_NAMESPACE"
    assert not (account.rec / "aws.argv").exists(), (
        f"aws was called before the namespace was known: {account.text('aws.argv')}"
    )


def test_bootstrap_refuses_without_an_account_or_a_region(scratch: Path) -> None:
    """Either coordinate unset is exit 2 naming it, with not one aws call."""
    for missing in ("DJB_VERIFIER_ACCOUNT", "DJB_VERIFIER_REGION"):
        made = open_account(scratch / f"no_{missing}")
        rc, out = made.bootstrap("--confirm", drop=(missing,))
        assert rc == 2, f"{missing} unset: wanted exit 2, got {rc}\n{report(made, out)}"
        assert missing in out, f"{missing} unset: the refusal does not name the variable"
        assert not (made.rec / "aws.argv").exists(), (
            f"{missing} unset: aws was called anyway — {made.text('aws.argv')}"
        )


def test_the_owners_hand_is_a_command_the_tree_actually_spells() -> None:
    """Every invocation the header shows, and the runbook, carries all three required variables."""
    want = ("DJB_DEPLOY_NAMESPACE", "DJB_VERIFIER_ACCOUNT", "DJB_VERIFIER_REGION")
    header = []
    for line in read(BOOTSTRAP).splitlines():
        if line == "set -euo pipefail":
            break
        header.append(re.sub(r"^# {0,3}", "", line))
    logical, pending = [], ""
    for line in header:
        pending += line
        if pending.endswith("\\"):
            pending = pending[:-1] + " "
            continue
        logical.append(pending)
        pending = ""
    if pending:
        logical.append(pending)
    invocations = [
        x for x in logical if re.search(r"\./deploy/iam/verifier_bootstrap\.sh( +--[a-z-]+)* *$", x)
    ]
    assert invocations, "the header shows no invocation of the script at all"
    broken = [
        f"'{x}' is missing: {' '.join(v for v in want if v not in x)}"
        for x in invocations
        if any(v not in x for v in want)
    ]
    assert not broken, "the header shows a command that would exit 2 before it did anything:\n" + (
        "\n".join(broken)
    )
    runbook = ROOT / "docs/runbooks/deploy.md"
    assert runbook.is_file(), "docs/runbooks/deploy.md is not in this tree"
    missing = [v for v in want if v not in runbook.read_text()]
    assert not missing and "verifier_bootstrap.sh" in runbook.read_text(), (
        "the runbook does not carry the owner's hand — missing: "
        f"{' '.join(missing) or 'the script itself'}"
    )


def test_bootstrap_refuses_without_confirm_and_creates_nothing(account: Account) -> None:
    """No --confirm is exit 2 with zero create/attach calls."""
    rc, out = account.bootstrap()
    assert rc == 2, f"wanted exit 2 without --confirm, got {rc}\n{report(account, out)}"
    creates = account.calls(CREATES)
    assert creates == 0, f"{creates} create/attach call(s) recorded on the refusal path"


def test_bootstrap_prints_its_whole_plan_before_it_refuses(account: Account) -> None:
    """The refusal's plan names every resource, prints every statement and numbers the clauses."""
    _, out = account.bootstrap()
    misses = [
        w
        for w in (
            f"{NAMESPACE}-verifier-ops",
            f"{NAMESPACE}-verifier-box",
            "AmazonSSMManagedInstanceCore",
            f"djb:namespace={NAMESPACE}",
            "access key",
        )
        if w not in out
    ]
    assert not misses, f"the plan does not name: {misses}\n{report(account, out)}"
    printed = count_lines(out, r"^ +[A-Za-z0-9]+ +(Allow|Deny) ")
    assert printed == len(statements()), (
        f"{len(statements())} statements in the document, {printed} printed in the plan"
    )
    assert re.search(r"^ *1[.)] ", out, re.M) and re.search(r"^ *8[.)] ", out, re.M), (
        "the plan does not number the eight policy clauses"
    )


def test_bootstrap_refuses_a_foreign_account(account: Account) -> None:
    """A caller that is not the pinned account is exit 2, names it, and creates nothing."""
    account.answer("account", "999999999999")
    rc, out = account.bootstrap("--confirm")
    assert rc == 2, f"wanted exit 2 on a foreign account, got {rc}\n{report(account, out)}"
    assert account.calls(CREATES) == 0, "create/attach call(s) recorded against a foreign account"
    assert "999999999999" in out, "the refusal does not name the account it found"


def test_bootstrap_first_run_creates_each_resource_exactly_once(account: Account) -> None:
    """A first run makes each of the ten creating calls exactly once."""
    rc, out = account.bootstrap("--confirm")
    assert rc == 0, f"the first run exited {rc}\n{report(account, out)}"
    wrong = [
        f"'{pair}' x{account.calls('^' + pair)}"
        for pair in (
            "iam create-policy",
            "iam create-user",
            "iam attach-user-policy",
            "iam create-role",
            "iam create-instance-profile",
            "iam add-role-to-instance-profile",
            "iam attach-role-policy",
            "ec2 create-security-group",
            "ec2 create-tags",
            "iam create-access-key",
        )
        if account.calls("^" + pair) != 1
    ]
    assert not wrong, f"wanted exactly 1 of each: {wrong}\n{report(account, out)}"


def test_bootstrap_never_opens_an_ingress_rule(account: Account) -> None:
    """No authorize-security-group call, and the group is made in a named VPC."""
    _, out = account.bootstrap("--confirm")
    opened = account.calls("authorize-security-group")
    assert opened == 0, f"{opened} authorize-security-group call(s)\n{report(account, out)}"
    group = [x for x in account.text("aws.argv").splitlines() if "ec2 create-security-group" in x]
    assert any("--vpc-id" in x for x in group), f"create-security-group names no --vpc-id: {group}"


def test_bootstrap_attaches_only_the_ssm_managed_policy_to_the_box_role(account: Account) -> None:
    """The box role's one attachment is AmazonSSMManagedInstanceCore; no secrets or backup grant."""
    account.bootstrap("--confirm")
    argv = account.text("aws.argv")
    attaches = [x for x in argv.splitlines() if "iam attach-role-policy" in x]
    assert len(attaches) == 1, f"wanted exactly one attach-role-policy, got: {attaches}"
    assert "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" in attaches[0], (
        f"the box role's attached policy is not AmazonSSMManagedInstanceCore: {attaches}"
    )
    assert not count_lines(
        argv,
        r"attach-role-policy.*(secretsmanager|backup)|iam-instance-profile.*(secretsmanager|backup)",
    ), "the bootstrap attaches a secrets or backup grant to the verifier box role"


def test_bootstrap_second_run_creates_nothing_and_mints_no_second_key(account: Account) -> None:
    """Everything existing: exit 0, no creating call, no second key, and it says what it found."""
    account.answer("mode", "exists")
    rc, out = account.bootstrap("--confirm")
    assert rc == 0, f"the second run exited {rc}\n{report(account, out)}"
    creates = account.calls(r"^(iam|ec2) (create|attach|add-role)-")
    assert creates == 0, f"{creates} creating call(s) on a second run\n{report(account, out)}"
    keys = account.calls("create-access-key")
    assert keys == 0, f"{keys} create-access-key call(s) on a second run"
    assert "exists" in out, f"the second run does not report the resources as existing\n{out}"


def test_bootstrap_says_an_existing_policy_is_not_updated_by_a_re_run(account: Account) -> None:
    """A re-run prints the publish command over a rendered document, and does not run it."""
    account.answer("mode", "exists")
    rc, out = account.bootstrap("--confirm")
    assert rc == 0, f"the second run exited {rc}\n{report(account, out)}"
    assert "iam create-policy-version" in out, (
        f"nothing tells the owner the account may be enforcing an older document\n{out}"
    )
    assert "--set-as-default" in out, "the printed command does not carry --set-as-default"
    named = re.findall(r"file://[^ \n]+", out)
    path = Path(named[-1][len("file://") :]) if named else None
    assert path is not None and path.is_file() and '"Version"' in path.read_text(), (
        f"the printed command names no readable rendered policy document (got '{path or 'none'}')"
    )
    assert "${ACCOUNT_ID}" not in path.read_text(), (
        "the document it points at still carries the ${ACCOUNT_ID} slot — it is the tracked file"
    )
    versions = account.calls("create-policy-version")
    assert versions == 0, f"{versions} create-policy-version call(s): the script published itself"


def test_the_bootstrap_summarises_the_policy_on_the_checkouts_own_interpreter(
    account: Account,
) -> None:
    """The plan's summary runs, and never through the `python3` first on PATH."""
    shim = '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$REC/python3.argv"\nexec /usr/bin/python3 "$@"\n'
    account.stubs.plant("python3", shim)
    rc, out = account.bootstrap()
    assert rc == 2, f"the bare run exited {rc}, not the refusal that prints the plan\n{out}"
    assert "verifier-ops-policy.json" in out and re.search(r"Allow|Deny", out), (
        f"the plan has no policy summary in it — the assertion below would be about nothing\n{out}"
    )
    via_path = count_lines(account.text("python3.argv"), re.escape("policy_summary.py"))
    assert via_path == 0, (
        f"{via_path} invocation(s) of policy_summary.py went through the PATH python3"
    )
    assert '"$CHECKOUT_PYTHON" "$SUMMARY"' in read(BOOTSTRAP), (
        "the bootstrap no longer runs the summary through CHECKOUT_PYTHON"
    )


def test_the_bootstrap_refuses_a_checkout_with_no_interpreter(
    account: Account, deploy_scaffold: DeployScaffold
) -> None:
    """A copy in a tree with no .venv is exit 2 naming the interpreter and setup.sh; none made."""
    fake = account.root / "fake-checkout"
    (fake / "deploy/iam").mkdir(parents=True)
    for relative in (BOOTSTRAP, POLICY, TRUST, SUMMARY):
        shutil.copy2(ROOT / relative, fake / relative)
    deploy_scaffold.into(fake)
    assert not (fake / ".venv").exists(), "the victim tree has a venv — it cannot drive the refusal"
    rc, out = account.bootstrap("--confirm", script=fake / BOOTSTRAP)
    assert rc == 2, f"wanted exit 2 in a checkout with no venv, got {rc}\n{report(account, out)}"
    assert ".venv/bin/python" in out and "setup.sh" in out, (
        f"the refusal does not name the interpreter or the remedy: {out[:300]}"
    )
    creates = account.calls("create-")
    assert creates == 0, f"{creates} create-* call(s) happened before the interpreter was checked"


def existing(account: Account, version: str | None = None) -> None:
    """Mark everything existing with the live policy equal to this tree's, at `version`."""
    account.answer("mode", "exists")
    account.answer("policy.live", rendered_policy())
    if version is not None:
        account.answer("policy.version", version)


def test_bootstrap_prints_the_box_roles_registry_grant_and_attaches_nothing(
    account: Account,
) -> None:
    """An absent registry grant prints put-role-policy over this module's composition, unmade."""
    existing(account, "v2")
    rc, out = account.bootstrap("--confirm")
    assert rc == 0, f"the run exited {rc}\n{report(account, out)}"
    assert (
        "iam put-role-policy" in out
        and f"--policy-name {NAMESPACE}-verifier-box-ecr" in out
        and f"--role-name {NAMESPACE}-verifier-box" in out
    ), f"the absent grant printed no put-role-policy for the box role\n{out}"
    assert account.calls("iam put-role-policy") == 0, "put-role-policy was MADE by the bootstrap"
    named = [
        x.split("file://", 1)[1].replace(" ", "")
        for x in out.splitlines()
        if "--policy-document file://" in x
    ]
    rendered = Path(named[0]) if named else None
    assert rendered is not None and rendered.is_file(), (
        f"the printed command names no readable rendered document ({named or '<none>'})"
    )
    assert json.loads(rendered.read_text()) == rendered_ecr_policy(), (
        f"the rendered grant differs from the derived document:\n{rendered.read_text()}"
    )
    assert not re.search(r'Delete|\*:\*|"ecr:\*"', rendered.read_text()), (
        f"the grant carries a delete or a wildcard action: {rendered.read_text()}"
    )


def test_bootstrap_prints_no_registry_grant_when_the_role_already_carries_it(
    account: Account,
) -> None:
    """A live grant equal to the composition prints nothing to do, says so, and was read first."""
    existing(account, "v2")
    account.answer("rolepolicy.live", json.dumps(rendered_ecr_policy()))
    rc, out = account.bootstrap("--confirm")
    assert rc == 0, f"the run exited {rc}\n{report(account, out)}"
    assert "iam put-role-policy" not in out, (
        f"it printed the attach command over a grant the role already carries\n{out}"
    )
    assert f"registry grant {NAMESPACE}-verifier-box-ecr" in out and "up to date" in out, (
        f"it does not say the live grant is current\n{out}"
    )
    assert account.calls("iam get-role-policy") >= 1, (
        "no iam get-role-policy call was made — the verdict was a guess"
    )


def test_bootstrap_prints_no_policy_version_when_the_live_one_already_agrees(
    account: Account,
) -> None:
    """A live version equal to the tree's document prints no publish and names the version."""
    existing(account, "v2")
    rc, out = account.bootstrap("--confirm")
    assert rc == 0, f"the run exited {rc}\n{report(account, out)}"
    assert "iam create-policy-version" not in out, (
        f"it printed the publish command over a live version that IS this tree's document\n{out}"
    )
    assert "up to date" in out and "v2" in out, (
        f"it does not say the live version is current, or does not name it\n{out}"
    )
    assert account.calls("iam get-policy-version") >= 1, (
        "no iam get-policy-version call — nothing was compared"
    )


def test_bootstrap_prints_the_policy_version_when_the_live_one_differs(account: Account) -> None:
    """A live document one statement short gets the publish command, names v1, unpublished."""
    existing(account, "v1")
    drifted = json.loads(rendered_policy())
    drifted["Statement"] = drifted["Statement"][:-1]
    account.answer("policy.live", json.dumps(drifted))
    rc, out = account.bootstrap("--confirm")
    assert rc == 0, f"the run exited {rc}\n{report(account, out)}"
    assert "iam create-policy-version" in out and "--set-as-default" in out, (
        f"the account is enforcing a document this tree does not carry and nothing said so\n{out}"
    )
    assert "OUT OF DATE" in out and "v1" in out, f"it does not name the stale live version\n{out}"
    assert account.calls("create-policy-version") == 0, (
        "the script published a policy version itself"
    )


def test_bootstrap_names_the_spot_service_linked_role_when_the_account_lacks_it(
    account: Account,
) -> None:
    """No Spot role: the create command under the admin profile, the error named; none made."""
    existing(account)
    account.answer("spot-slr", "absent")
    rc, out = account.bootstrap("--confirm")
    assert rc == 0, f"the run exited {rc}\n{report(account, out)}"
    assert "create-service-linked-role --aws-service-name spot.amazonaws.com" in out, (
        f"an account with no Spot service-linked role gets no mention of it\n{out}"
    )
    assert "ServiceLinkedRoleCreationNotPermitted" in out, (
        "it does not name the failure code the operator will actually see"
    )
    assert "--profile default" in out, f"the printed command names no admin profile\n{out}"
    assert account.calls("create-service-linked-role") == 0, (
        "the script created an account-wide service-linked role"
    )


def test_bootstrap_says_nothing_to_do_when_the_spot_role_exists(account: Account) -> None:
    """An existing Spot role is reported checked, with no command."""
    existing(account)
    account.answer("spot-slr", "exists")
    rc, out = account.bootstrap("--confirm")
    assert rc == 0, f"the run exited {rc}\n{report(account, out)}"
    assert "create-service-linked-role" not in out, (
        f"it printed the create command for a role that already exists\n{out}"
    )
    assert "AWSServiceRoleForEC2Spot exists" in out, (
        f"the run says nothing about the Spot role\n{out}"
    )


def test_bootstrap_prints_the_secret_on_the_last_line_and_nowhere_else(account: Account) -> None:
    """The minted secret appears once, on the last line, and in no recorded argv."""
    _, out = account.bootstrap("--confirm")
    marker = "driveOnly" + "NotARealSecret0000000000000000"
    hits = count_lines(out, re.escape(marker))
    assert hits == 1, f"the secret appears {hits} time(s) in the output"
    last = out.splitlines()[-1] if out.splitlines() else ""
    assert marker in last, f"the last line is not the one carrying the secret: '{last}'"
    assert marker not in account.text("aws.argv"), (
        "the secret was passed as an argument to an aws call — it would land in ps and a history"
    )


def test_bootstrap_refuses_a_piped_stdout(account: Account) -> None:
    """A piped stdout is exit 2 and creates nothing."""
    env = account.env()
    with subprocess.Popen(
        ["bash", str(ROOT / BOOTSTRAP), "--confirm"],
        env=env,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ) as piped:
        out = piped.communicate()[0].decode(errors="replace")
    assert piped.returncode == 2, f"wanted exit 2 on a piped stdout, got {piped.returncode}\n{out}"
    assert "refuses pipes" in out, f"the exit 2 is some other refusal, not the pipe guard's:\n{out}"
    creates = account.calls(r"(create|attach|add-role)-")
    assert creates == 0, f"{creates} creating call(s) on the piped run"


# the bake recipe

PLAN_TOOLS = ("dnf", "yum", "docker", "git", "uv", "systemctl", "useradd", "install", "cloud-init")


def bake_plan(
    scratch: Path, recorders: Sequence[str] = (), rec: bool = True
) -> tuple[int, str, Path]:
    """`bake.sh --plan` in a pen whose bin holds `recorders`; its exit, text and the pen."""
    pen = scratch / "pen"
    (pen / "rec").mkdir(parents=True, exist_ok=True)
    stubs = stubs_at(pen / "bin", {tool: recorder(tool) for tool in recorders})
    env = {"PATH": f"{stubs.bin}:{BASE_PATH}", "HOME": str(pen)}
    if rec:
        env["REC"] = str(pen / "rec")
    rc, out = run(["bash", str(ROOT / BAKE), "--plan"], env)
    return rc, out, pen


def fenced(text: str, name: str) -> str:
    """Every line from `# >>> <name> >>>` to `# <<< <name> <<<`, both kept — `sed -n '/a/,/b/p'`."""
    kept, inside = [], False
    for line in text.splitlines():
        if line == f"# >>> {name} >>>":
            inside = True
        if inside:
            kept.append(line)
        if inside and line == f"# <<< {name} <<<":
            inside = False
    return "\n".join(kept)


BODY_CHECK = r'^\[ -d "\$BAKE_CHECKOUT/\.git" \]'
BODY_PARK = r'^\(cd "\$BAKE_CHECKOUT".*checkout -B'
BODY_SETUP = r'^\(cd "\$BAKE_CHECKOUT".*scripts/setup\.sh'


def test_the_recipe_installs_no_package_amazon_linux_does_not_have(scratch: Path) -> None:
    """Neither the dnf line nor the plan names docker-compose-plugin, which AL2023 lacks."""
    dnf = [x for x in read(BAKE).splitlines() if re.search(r"^sudo dnf install", x)]
    assert dnf, "the recipe has no 'sudo dnf install' line at all"
    assert not any("docker-compose-plugin" in x for x in dnf), (
        f"step 1 still installs 'docker-compose-plugin', which AL2023 does not have: {dnf}"
    )
    rc, out, _ = bake_plan(scratch)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    assert "docker-compose-plugin" not in out, (
        "the plan still names the docker-compose-plugin package"
    )


def test_the_compose_plugin_is_pinned_and_checksummed_before_it_is_installed(scratch: Path) -> None:
    """Version and sha256 knobs beside uv's, the URL from the knob, verified before runnable."""
    body = read(BAKE)
    ver_n = line_no(body, r"^BAKE_COMPOSE_VERSION=")
    sha_n = line_no(body, r"^BAKE_COMPOSE_SHA256=")
    uv_n = line_no(body, r"^BAKE_UV_VERSION=")
    assert ver_n and sha_n, f"no BAKE_COMPOSE_VERSION / BAKE_COMPOSE_SHA256 knob ({ver_n}, {sha_n})"
    assert uv_n and ver_n > uv_n and ver_n - uv_n < 40, (
        f"BAKE_COMPOSE_VERSION is at :{ver_n} and BAKE_UV_VERSION at :{uv_n} — the two pins"
        " must read together"
    )
    urls = [x for x in body.splitlines() if "docker-compose-linux-aarch64" in x]
    assert urls, "the recipe never names the aarch64 compose asset — these boxes are arm64 (c7g)"
    assert "${BAKE_COMPOSE_VERSION}" in urls[0], (
        f"the compose URL does not interpolate BAKE_COMPOSE_VERSION: {urls[0]}"
    )
    lines = body.splitlines()
    verify = [
        n
        for n, x in enumerate(lines, 1)
        if re.search(r"BAKE_COMPOSE_SHA256|shasum|sha256sum", x)
        and not x.startswith("#")
        and not x.startswith("BAKE_COMPOSE_SHA256=")
    ]
    install = [
        n
        for n, x in enumerate(lines, 1)
        if re.search(r"install -m 0755 .*BAKE_COMPOSE_PLUGIN|chmod \+x .*BAKE_COMPOSE_PLUGIN", x)
        and not x.startswith("#")
    ]
    assert line_no(body, "/usr/local/lib/docker/cli-plugins"), (
        "the plugin does not land in /usr/local/lib/docker/cli-plugins — docker will not find it"
    )
    assert verify and install, f"no checksum step ({verify}) or no install step ({install})"
    assert verify[0] < install[-1], (
        f"the checksum is at :{verify[0]} and the install at :{install[-1]} — an unverified"
        " binary is already in place"
    )
    rc, out, _ = bake_plan(scratch)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    assert "cli-plugins" in out and "sha256" in out, (
        f"the plan does not name the cli-plugins path and the sha256 step\n{out}"
    )


def test_bake_plan_runs_nothing_and_names_its_steps_in_order(scratch: Path) -> None:
    """--plan runs none of the nine tools and names its six load-bearing steps in order."""
    rc, out, pen = bake_plan(scratch, PLAN_TOOLS)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    ran = pen / "rec/ran"
    assert not (ran.is_file() and ran.stat().st_size), f"--plan ran something: {ran.read_text()}"
    steps = (
        r"uv sync --frozen|\./scripts/setup\.sh|docker compose pull|DJB_GATE_SLOTS=2"
        r"|verifier-parking|cloud-init clean"
    )
    order: list[str] = []
    for line in out.splitlines():
        found = re.match(f".*({steps}).*", line)
        if found and found.group(1) not in order:
            order.append(found.group(1))
    want = [
        "verifier-parking",
        "uv sync --frozen",
        "./scripts/setup.sh",
        "docker compose pull",
        "DJB_GATE_SLOTS=2",
        "cloud-init clean",
    ]
    assert order == want, f"the plan's step order is {order}, wanted {want}\n{out}"


def test_the_bake_parks_before_it_sets_up(scratch: Path) -> None:
    """Body and plan alike: the guarded park before setup.sh, and the plan says why."""
    body = read(BAKE)
    b_check, b_park, b_setup = (line_no(body, p) for p in (BODY_CHECK, BODY_PARK, BODY_SETUP))
    assert b_park and b_setup, f"the recipe has no park ({b_park}) or no setup.sh step ({b_setup})"
    assert b_park < b_setup, f"the body parks at :{b_park}, AFTER ./scripts/setup.sh at :{b_setup}"
    assert b_check and b_check < b_park, (
        f"the checkout guard is at '{b_check}' and the park at '{b_park}' — the park must"
        " stand on a guarded checkout"
    )
    rc, out, _ = bake_plan(scratch, rec=False)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    p_park, p_setup = (
        line_no(out, "verifier-parking"),
        line_no(out, re.escape("./scripts/setup.sh")),
    )
    assert p_park and p_setup and p_park < p_setup, (
        f"the plan names the park at '{p_park}' and ./scripts/setup.sh at '{p_setup}'\n{out}"
    )
    assert "DATABASE_NAME" in out and "derive" in out, (
        f"the plan gives no reason for the park preceding the stack step\n{out}"
    )


def test_the_bake_writes_no_database_pin(scratch: Path) -> None:
    """No pin defined, bracketed, spelled or planned — and the park that makes it right stands."""
    body = read(BAKE)
    pins = count_lines(body, "pin_database_name")
    assert pins == 0, f"the recipe still carries {pins} mention(s) of pin_database_name"
    assert ">>> the database pin >>>" not in body, (
        "the recipe still brackets a database-pin block a drive would extract and run"
    )
    markers = count_lines(body, "# pinned")
    assert markers == 0, f"the recipe still spells the .env marker {markers} time(s)"
    rc, out, _ = bake_plan(scratch, rec=False)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    assert "pin_database_name" not in out and "# pinned" not in out, (
        "the plan still describes pinning the .env"
    )
    b_park, b_setup = line_no(body, BODY_PARK), line_no(body, BODY_SETUP)
    assert b_park and b_setup and b_park < b_setup, (
        f"the pin is gone and the park is at '{b_park}' against a stack step at '{b_setup}'"
    )


def test_the_bake_publishes_the_template(scratch: Path) -> None:
    """The template published between setup and pull, as the bake user; a failed one stops."""
    rc, out, _ = bake_plan(scratch, rec=False)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    p_setup = line_no(out, re.escape("./scripts/setup.sh"))
    p_tmpl = line_no(out, "db_template_refresh")
    p_pull = line_no(out, "docker compose pull")
    assert p_tmpl and p_setup and p_pull and p_setup <= p_tmpl < p_pull, (
        f"the plan names db_template_refresh at '{p_tmpl}' against setup '{p_setup}'"
        f" and pull '{p_pull}'"
    )
    block = fenced(read(BAKE), "the stack")
    assert block, "the recipe has no '# >>> the stack >>>' block — step 10's body is not reachable"
    pen = scratch / "tmpl"
    src = pen / "src"
    (pen / "rec").mkdir(parents=True)
    stubs_at(
        pen / "bin",
        {
            "sudo": '#!/usr/bin/env bash\nprintf \'%s\\n\' "sudo $*" >>"$REC/ran"\n'
            '[ "${1:-}" = "-u" ] && shift 2\nexec "$@"\n'
        },
    )
    (src / "scripts").mkdir(parents=True)
    (src / "scripts/setup.sh").write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "setup" >>"$REC/calls"\n'
    )
    (src / "scripts/setup.sh").chmod(0o755)
    (src / "scripts/db.sh").write_text(
        "db_template_refresh() {\n"
        '    printf \'%s %s\\n\' "db_template_refresh" "$(pwd -P)" >>"$REC/calls"\n'
        '    return "$(cat "$REC/refresh.rc" 2>/dev/null || echo 0)"\n'
        "}\n"
    )
    (pen / "run.sh").write_text(f'set -euo pipefail\n{block}\necho "after the stack"\n')
    env = {
        "PATH": f"{pen}/bin:{BASE_PATH}",
        "HOME": str(pen),
        "REC": str(pen / "rec"),
        "BAKE_CHECKOUT": str(src),
        "BAKE_USER": "verifier",
    }
    rc, out = run(["bash", str(pen / "run.sh")], env)
    calls_file = pen / "rec/calls"
    recorded = calls_file.read_text() if calls_file.is_file() else ""
    calls = [x.split(" ")[0] for x in recorded.splitlines()]
    assert rc == 0 and calls == ["setup", "db_template_refresh"], (
        f"the stack block exited {rc} with calls {calls}, wanted setup then"
        f" db_template_refresh: {out}"
    )
    assert f"db_template_refresh {src.resolve()}" in recorded, (
        f"the publish did not run in $BAKE_CHECKOUT: {recorded}"
    )
    sudos = count_lines((pen / "rec/ran").read_text(), "^sudo -u verifier ")
    assert sudos == 2, f"wanted two 'sudo -u verifier' calls, recorded {sudos}"
    calls_file.unlink()
    (pen / "rec/ran").unlink()
    (pen / "rec/refresh.rc").write_text("1\n")
    rc, out = run(["bash", str(pen / "run.sh")], env)
    assert rc != 0 and "after the stack" not in out, (
        f"a failed publish exited {rc} and the recipe walked on: {out}"
    )


def test_the_bake_installs_the_frontend_toolchain(scratch: Path) -> None:
    """Node pinned and checked before unpack, pnpm from packageManager, installed in order."""
    body = read(BAKE)
    block = fenced(body, "the frontend toolchain")
    assert block, "the recipe carries no sentinelled frontend-toolchain block"
    ver_n, sha_n = line_no(body, r"^BAKE_NODE_VERSION="), line_no(body, r"^BAKE_NODE_SHA256=")
    assert ver_n and sha_n, f"BAKE_NODE_VERSION is at '{ver_n}' and BAKE_NODE_SHA256 at '{sha_n}'"
    assert any(
        re.search(r"\$\{?BAKE_NODE_VERSION", x) for x in block.splitlines() if "nodejs.org" in x
    ), "the block's nodejs.org URL does not read BAKE_NODE_VERSION"
    b_sha, b_unpack = line_no(block, "sha256sum -c"), line_no(block, r"tar -x[zJ]f")
    assert b_sha and b_unpack and b_sha < b_unpack, (
        f"the checksum is at '{b_sha}' and the unpack at '{b_unpack}' — an unverified"
        " runtime would already be on the image"
    )
    assert "packageManager" in block, "the block never reads packageManager"
    typed = count_lines(block, r"pnpm@[0-9]")
    assert typed == 0, f"the block spells a literal pnpm version {typed} time(s)"
    pinned = re.search(
        r'"packageManager"\s*:\s*"([^"]*)"', (ROOT / "frontend/package.json").read_text()
    )
    assert pinned and re.match(r"pnpm@[0-9]", pinned.group(1)), (
        "frontend/package.json's packageManager is "
        f"'{pinned and pinned.group(1)}' — not a pnpm@<version>"
    )
    b_check = line_no(body, BODY_CHECK)
    b_call = line_no(body, r"^install_frontend_toolchain$")
    b_setup = line_no(body, BODY_SETUP)
    assert b_call and b_setup and b_check and b_check < b_call < b_setup, (
        f"the install call is at '{b_call}', the checkout guard at '{b_check}',"
        f" the stack step at '{b_setup}'"
    )
    rc, out, _ = bake_plan(scratch, rec=False)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    assert "node" in out and "pnpm" in out and "sha256" in out, (
        f"the plan does not name the frontend toolchain it installs\n{out}"
    )


def test_bake_removes_its_marker_after_the_work_and_before_the_clean(scratch: Path) -> None:
    """Plan and body alike: the marker leaves after the last working step, before the clean."""
    rc, out, _ = bake_plan(scratch)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    work_n, clean_n = line_no(out, "DJB_GATE_SLOTS=2"), line_no(out, "cloud-init clean")
    drop_n = line_no(out, "/etc/verifier/bake")
    assert drop_n, (
        "the plan never says the bake marker is removed — it would be captured into the image"
    )
    assert work_n and clean_n and work_n < drop_n < clean_n, (
        f"the plan's marker removal is at line {drop_n}; the last working step {work_n},"
        f" clean {clean_n}\n{out}"
    )
    body = read(BAKE)
    b_work = line_no(body, r'^step "[0-9]+/[0-9]+ environment')
    b_clean = line_no(body, r"^sudo cloud-init clean")
    b_drop = line_no(body, r'^sudo rm -f "\$BAKE_MARKER"')
    assert b_drop, "the recipe body never removes $BAKE_MARKER"
    assert b_work and b_clean and b_work < b_drop < b_clean, (
        f"the body's removal is at :{b_drop}; the last working step :{b_work}, clean :{b_clean}"
    )


def test_the_plan_is_never_mistaken_for_a_finished_bake(scratch: Path) -> None:
    """The plan never prints the success line the wrapper scrapes; the real path still does."""
    rc, out, _ = bake_plan(scratch)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    assert "ready for create-image" not in out, (
        "the plan prints the success line the wrapper scrapes"
    )
    assert line_no(read(BAKE), r'^say "ready for create-image"'), (
        "the recipe's real path no longer prints the success line at all"
    )


SUDO_SHIM = r"""#!/usr/bin/env bash
printf '%s\n' "sudo $*" >>"$REC/ran"
if [ "${1:-}" = "-n" ]; then
    exit "$(cat "$REC/sudo-n.rc" 2>/dev/null || echo 0)"
fi
exit 0
"""
SUDO_TOOLS = (
    "dnf",
    "systemctl",
    "useradd",
    "usermod",
    "curl",
    "install",
    "id",
    "sha256sum",
    "docker",
)


def test_the_recipe_refuses_a_bake_box_it_cannot_sudo_on(scratch: Path) -> None:
    """`sudo -n true` refused is exit 2 before step 1, naming the rule; allowed reaches step 6."""
    pen = scratch / "bake-sudo"
    (pen / "rec").mkdir(parents=True)
    (pen / "etc/verifier").mkdir(parents=True)
    (pen / "etc/verifier/bake").write_text("a bake box\n")
    stubs_at(pen / "bin", {**{tool: recorder(tool) for tool in SUDO_TOOLS}, "sudo": SUDO_SHIM})
    nocheckout = pen / "no-such-checkout"
    env = {
        "PATH": f"{pen}/bin:{BASE_PATH}",
        "HOME": str(pen),
        "REC": str(pen / "rec"),
        "VERIFIER_ROOT": str(pen),
        "DJB_VERIFIER_CHECKOUT": str(nocheckout),
    }
    (pen / "rec/sudo-n.rc").write_text("1\n")
    rc, out = run(["bash", str(ROOT / BAKE)], env)
    ran = (pen / "rec/ran").read_text() if (pen / "rec/ran").is_file() else ""
    assert rc == 2, f"wanted exit 2 when `sudo -n true` refuses, got {rc}\n{out}"
    assert not line_no(out, r"^== bake step"), (
        f"the recipe printed a step banner before it refused:\n{out}"
    )
    assert "NOPASSWD" in out and BAKE_SEAM in out, (
        f"the refusal does not name the rule and the file that grants it: {out}"
    )
    assert not line_no(ran, r"^sudo dnf "), (
        "it ran `sudo dnf install` anyway: the refusal is not CLOSED"
    )
    assert line_no(ran, r"^sudo -n "), f"the recipe's probe is not `sudo -n`. recorded: {ran}"
    (pen / "rec/ran").unlink()
    (pen / "rec/sudo-n.rc").write_text("0\n")
    assert not (nocheckout / ".git").exists(), f"the pen's checkout path {nocheckout} holds a .git"
    rc, out = run(["bash", str(ROOT / BAKE)], env)
    ran = (pen / "rec/ran").read_text() if (pen / "rec/ran").is_file() else ""
    assert line_no(ran, r"^sudo dnf "), (
        f"the recipe refused a box whose `sudo -n true` succeeds: {out}"
    )
    assert "no checkout at" in out, (
        f"wanted the step-6 checkout refusal after the sudo guard passed: {out}"
    )


def test_the_bake_users_root_leaves_with_the_bake(scratch: Path) -> None:
    """The launch seam grants no sudo; the recipe drops the bake rule after the clean, gone."""
    granted = [x for x in render_seam().splitlines() if re.search(r"^\s*sudo:", x)]
    assert not granted, f"the launch seam grants a sudo rule: {granted}"
    rc, out, _ = bake_plan(scratch, rec=False)
    assert rc == 0, f"--plan exited {rc}\n{out}"
    assert "sudoers.d" in out, "the plan never says the sudo rule leaves with the bake"
    body = read(BAKE)
    b_clean = line_no(body, r"^sudo cloud-init clean")
    b_drop = line_no(body, r'^sudo rm -f "\$BAKE_SUDOERS"')
    assert b_drop, "the recipe body never removes the bake account's sudo drop-in"
    assert b_clean and b_drop > b_clean, (
        f"the body removes the sudo rule at :{b_drop}, at or above the clean at :{b_clean}"
    )
    after = "\n".join(body.splitlines()[b_drop - 1 :])
    assert "sudo -n true" in after, "nothing after the removal checks that it worked"


def test_bake_refuses_to_run_anywhere_but_a_bake_box(scratch: Path) -> None:
    """No marker is exit 2; the marker is the bake seam's; an unknown flag is exit 2."""
    pen = scratch / "bake-refuse"
    (pen / "bin").mkdir(parents=True)
    (pen / "rec").mkdir()
    env = {"PATH": f"{pen}/bin:{BASE_PATH}", "HOME": str(pen), "REC": str(pen / "rec")}
    rc, out = run(["bash", str(ROOT / BAKE)], {**env, "VERIFIER_ROOT": str(pen)})
    assert rc == 2, f"wanted exit 2 off a bake box, got {rc}\n{out}"
    assert "/etc/verifier/bake" in read(BAKE) and "/etc/verifier/bake" in read(BAKE_SEAM), (
        "the recipe's bake marker and the bake user-data do not name the same file"
    )
    rc, out = run(["bash", str(ROOT / BAKE), "--nonsense"], env)
    assert rc == 2, f"wanted exit 2 on an unknown flag, got {rc}\n{out}"


# what must not move


def unfenced(directory: Path, gate: Path) -> int:
    """Deploy-layer drives in `directory` that `gate` does not invoke as a whole line."""
    wired = set(gate.read_text().splitlines())
    drives = sorted(p for p in directory.glob("test_*.sh") if p.is_file())
    return sum(1 for d in drives if f"./deploy/tests/{d.name}" not in wired)


def baseline(directory: Path, gate: Path) -> int:
    """Deploy-layer drives in `directory` minus `gate`'s column-zero invocation lines."""
    total = sum(1 for p in directory.glob("test_*.sh") if p.is_file())
    wired = count_lines(gate.read_text(), r"^\./deploy/tests/test_[A-Za-z0-9_]*\.sh$")
    return total - wired


def twin(name: str, directory: Path, gate: Path) -> int:
    """`test_verifier_box.sh`'s shell `name` run over `directory` and `gate`; what it prints."""
    text = (ROOT / "scripts/tests/test_verifier_box.sh").read_text().splitlines()
    starts = [n for n, x in enumerate(text) if x.startswith(f"{name}() {{")]
    if not starts:
        raise CouldNotLook(f"scripts/tests/test_verifier_box.sh defines no {name}()")
    end = text.index("}", starts[0])
    script = "\n".join([*text[starts[0] : end + 1], f'{name} "$1" "$2"'])
    rc, out = run(["bash", "-c", script, name, str(directory), str(gate)], {"PATH": BASE_PATH})
    if rc != 0 or not out.strip().isdigit():
        raise CouldNotLook(f"the shell {name} could not be run (exit {rc}): {out!r}")
    return int(out)


def test_the_deploy_layer_drives_nothing_invokes_are_unchanged(scratch: Path) -> None:
    """The gap's two derivations agree, move for an unfenced newcomer only, and match the twin's."""
    real_dir, real_gate = ROOT / "deploy/tests", ROOT / "scripts/check.sh"
    n, want = unfenced(real_dir, real_gate), baseline(real_dir, real_gate)
    assert n == want, (
        f"the per-file walk says {n}, the directory minus the gate's lines says {want}"
    )
    plants = {}
    for label, newcomer, wire in (("a", "test_x.sh", False), ("b", "test_y.sh", True)):
        plot = scratch / f"deploy-layer-{label}"
        plot.mkdir()
        for drive in real_dir.glob("test_*.sh"):
            shutil.copy2(drive, plot / drive.name)
        shutil.copy2(real_gate, plot / "check.sh")
        (plot / newcomer).write_text("")
        if wire:
            with (plot / "check.sh").open("a") as appended:
                appended.write(f"./deploy/tests/{newcomer}\n")
        plants[label] = plot
    moved = unfenced(plants["a"], plants["a"] / "check.sh")
    assert moved == want + 1, f"an unfenced newcomer left the gap at {moved}, wanted {want + 1}"
    held = unfenced(plants["b"], plants["b"] / "check.sh")
    assert held == want, f"a wired newcomer moved the gap to {held}, wanted {want}"
    if not (ROOT / "scripts/tests/test_verifier_box.sh").is_file():
        return
    for directory, gate in ((real_dir, real_gate), *((p, p / "check.sh") for p in plants.values())):
        mine = (unfenced(directory, gate), baseline(directory, gate))
        theirs = (
            twin("deploy_layer_unfenced", directory, gate),
            twin("deploy_layer_baseline", directory, gate),
        )
        assert mine == theirs, (
            f"the box drive's shell derivations say {theirs} over {directory.name},"
            f" this module {mine}"
        )
