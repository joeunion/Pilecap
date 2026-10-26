"""The proof from zero: a clone of the export made a product, three features down the SDK's road."""

# does-not-cover: a `--ref` other than this checkout's HEAD — publish exports a clean HEAD.
# does-not-cover: a builder's own waits — the scaffold writes; only the road is measured.
# does-not-cover: a product of many apps — one generated app and its one noun stand for it.
# does-not-cover: the clone's database and directory afterwards — printed, never removed here.
# does-not-cover: the reference's prose — `reference=` counts its pages and finds each shape named.

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.could_not_look import CouldNotLook
from quality.djb import env as djb_env
from quality.djb import ledger

ROOT = Path(__file__).resolve().parents[3]
#: The checkout whose `publish` module exports ROOT: the same tree outside a test.
CODE = Path(__file__).resolve().parents[3]
EXPORT = (
    "import sys; from pathlib import Path; from quality.djb.rituals.publish import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
REUSED = "reusing running stack"
NAMESPACE = "zzzproof"
PRODUCT_TREE = "a product tree declares a namespace: the proof from zero is the template's"
APP = "zzzproofs"
NOUN = "Proof"
SHAPE = "DJB_IDENTITY_SHAPE=platform_apps=own"  # pragma: allowlist secret
TIDIED = ("frontend/openapi.json", "frontend/src/api/generated/schema.d.ts", "quality/budgets.yaml")
BASE_REF = "refs/proof/base"
CLOUD_IDENTITY = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
LOOP_REASON = "proof: the scripted field test measures the builder's road"
SANCTION = f"{NAMESPACE}: the proof's one sanctioned stack edit"
IDENTITY = {"NAME": "proof-from-zero", "EMAIL": "proof-from-zero@localhost"}
FROZEN = "quality/gate.py"
STACKED = "pyproject.toml"
AROUND = "quality/x.py"
REFERENCE = "docs/sdk"
#: What the proof drives (the merge's lane step reads it); any other merge proves at night.
INPUTS = (
    ".github/workflows/proof-from-zero.yml",
    "apps/accounts/management/commands/seed.py",
    "apps/core/management/commands/declare.py",
    "apps/core/management/commands/newapp.py",
    "apps/core/management/commands/scaffold.py",
    "apps/core/scaffold/",
    f"{REFERENCE}/",
    "manage.py",
    "pilecap/",
    "pyproject.toml",
    "quality/djb/rituals/proof_from_zero.py",
    "quality/djb/rituals/publish.py",
    "quality/sdk/",
    "scripts/check.sh",
    "scripts/feature.sh",
    "scripts/proof_from_zero.sh",
    "scripts/publish.sh",
    "scripts/rung_tidy.sh",
    "scripts/serve.sh",
    "scripts/setup.sh",
    "scripts/worker.sh",
    "uv.lock",
)
READY_SECONDS = 120.0
DRIVE_WORDS = {0: "agree", 1: "disagree", 2: "unlooked"}
BYPASS = f"apps/{APP}/models.py"
BYPASS_LINE = "from apps.core import models as _bypass  # noqa: E402, F401\n"
PLANTS = {
    "forced-apps": (
        "quality/djb/scope.py",
        'FORCED_FULL = (\n    "quality/",\n',
        'FORCED_FULL = (\n    "apps/",\n    "quality/",\n',
    ),
    "sdk-bypass": (
        "quality/rules.yaml",
        '  - id: "96"\n    name: product-apps-import-the-sdk-only\n    enabled: true\n',
        '  - id: "96"\n    name: product-apps-import-the-sdk-only\n    enabled: false\n',
    ),
}
RULE_96 = (
    "from pathlib import Path\n"
    "from quality.checks.rule_96 import product_apps_import_the_sdk_only as judge\n"
    "from quality.engine.rules import RULES\n"
    "from quality.engine.run import apply_overrides\n"
    "rule = next(r for r in RULES if str(r['id']) == '96')\n"
    "kept, held = apply_overrides('96', judge(Path.cwd(), rule).findings)\n"
    "print(len(kept), len(held))\n"
    "for one in kept:\n"
    "    print(f'{one.path}:{one.line}: {one.msg}')\n"
)
SDK_VERSION = (
    "import os, django\n"
    "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')\n"
    "django.setup()\n"
    "import pilecap\n"
    "print(pilecap.__version__)\n"
)


@dataclass(frozen=True)
class Feature:
    """One shape: its `manage.py scaffold` words, the app it may touch and its subject."""

    tag: str
    words: tuple[str, ...]
    app: str
    subject: str


FEATURES = (
    Feature("a", ("filter", APP, NOUN, "notes=icontains"), APP, "proofs narrow by their notes"),
    Feature("b", ("field", APP, NOUN, "due_on:date?"), APP, "a proof carries the day it is due"),
    Feature("c", ("verb", APP, NOUN, "touch"), APP, "a proof can be touched"),
)
STEPS = (
    "export     publish --to <dest>.export of this checkout's HEAD (--ref): what a product gets",
    "clone      git clone <the export> <dest>; main at its one commit (a --plant commits here)",
    "setup      ./scripts/setup.sh in the clone, `manage.py seed` for the drive's tenant, then "
    f"setup.sh again on the running stack (`{REUSED}`)",
    f"declare    `manage.py declare {NAMESPACE}`: quality/local/rules.yaml and "
    "scripts/local/template-base, committed through the hook",
    f"product    `manage.py newapp {APP}`, `manage.py declare {NAMESPACE}` again "
    f"(.env += {SHAPE}), "
    f"`manage.py scaffold noun {APP} {NOUN}`, the client and "
    "budgets tidied; committed through the hook — the base every feature starts from",
    "features   each `manage.py scaffold <shape>` on that base, tidied and committed through the "
    "hook; `scope lane` line 1 == loop, touched within its app, `tax: 0 min`; rule 96 measured; "
    f"`feature.sh {APP} --loop --drive {NOUN}` on the migrated, running stack, exit 0",
    f"refusals   {FROZEN} refused; {STACKED} refused, then sanctioned with its trailer; "
    f"{AROUND} committed around the hook, named by `--fast`",
    f"record     {ledger.PROOF_RECORD} in the `{ledger.PROOF_SCHEMA}` grammar (ledger.proof_line)",
)


@dataclass
class Measured:
    """What one feature's road printed: lane, touched apps, tax, loop, rule 96 and the drive."""

    lane: str = "-"
    touched: list[str] = field(default_factory=list)
    tax: str = "-"
    loop_s: str = "-"
    scaffolded: bool = False
    rule96: tuple[int, int] | None = None
    drive: str = "-"
    failures: list[str] = field(default_factory=list)


class Died(CouldNotLook):
    """Exit 2: a step that could not be carried out, so nothing after it was measured."""


def out(text: str = "") -> None:
    print(text, flush=True)


def refuse_if_piped() -> None:
    """Exit 2 when stdout is a pipe outside CI: the exit is the verdict."""
    if os.environ.get("CI"):
        return
    try:
        piped = stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        piped = False
    if piped:
        raise Died("proof_from_zero refuses pipes — run it bare or redirect to a file.")


def drop_own_path() -> None:
    """The wrapper's `PYTHONPATH` entry withheld from every child this run starts."""
    entries = os.environ.get("PYTHONPATH", "").split(os.pathsep)
    kept = [e for e in entries if e and os.path.realpath(e) != str(ROOT)]
    if kept:
        os.environ["PYTHONPATH"] = os.pathsep.join(kept)
    else:
        os.environ.pop("PYTHONPATH", None)


def child_env(**extra: str) -> dict[str, str]:
    """This process's environment less the variables that would steer the clone's gate."""
    # Invariant: the clone is a laptop — its object store is its `.env`'s, never the runner's.
    held = ("GIT_", "DJB_LAYER_", "DJB_LOOP_", "DATABASE_NAME", "VIRTUAL_ENV", *CLOUD_IDENTITY)
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(held) and k not in djb_env.STEERS
    }
    return {**env, **extra}


class Proof:
    """The run: one clone, its steps in order, and the record they add up to."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.dest = Path(args.dest).resolve()
        self.out_dir = Path(args.out).resolve()
        self.measured = [Measured() for _ in FEATURES]
        self.refused = 0
        self.sanctioned = 0
        self.findings: list[str] = []
        self.source = ""
        self.tree = ""
        self.export_dir = self.dest.with_name(f"{self.dest.name}.export")
        self.sdk = "-"
        self.reference = "-"
        self.base_leaf = ""

    def run_logged(self, name: str, argv: Sequence[str], **env: str) -> tuple[int, str, float]:
        """`argv` in the clone, both streams to `<out>/<name>.log`; exit, text and seconds."""
        log = self.out_dir / f"{name}.log"
        start = time.monotonic()
        with log.open("w") as sink:
            try:
                rc = subprocess.run(
                    list(argv),
                    cwd=self.dest,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=child_env(**env),
                    check=False,
                ).returncode
            except OSError as exc:
                raise Died(f"{argv[0]} could not start in {self.dest}: {exc}") from exc
        return rc, log.read_text(errors="replace"), time.monotonic() - start

    def manage(self, name: str, *words: str) -> tuple[int, str]:
        """`manage.py <words>` in the clone, logged as `<name>.log`; exit and text."""
        rc, text, _ = self.run_logged(name, [".venv/bin/python", "manage.py", *words])
        return rc, text

    def git(self, *argv: str, **env: str) -> str:
        """`git <argv>` in the clone; its stdout, or Died naming what failed."""
        done = subprocess.run(
            ["git", *argv], cwd=self.dest, capture_output=True, text=True, env=child_env(**env)
        )
        if done.returncode != 0:
            raise Died(f"git {' '.join(argv)} in {self.dest}: {done.stderr.strip()}")
        return done.stdout.strip()

    def changed(self) -> list[str]:
        """Every path the working tree holds that HEAD does not, staged by name."""
        listed = self.git(
            "ls-files", "-z", "--modified", "--deleted", "--others", "--exclude-standard"
        )
        return sorted({entry for entry in listed.split("\0") if entry})

    def step(self, label: str, began: float, said: str) -> None:
        out(f"   [{time.monotonic() - began:.1f}s] {label}: {said}")

    def clone(self) -> None:
        """The export of the tree under proof, cloned with main at its commit; a plant on top."""
        began = time.monotonic()
        sha, head = (
            subprocess.run(
                ["git", "rev-parse", "--verify", f"{rev}^{{commit}}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            for rev in (self.args.ref, "HEAD")
        )
        if not sha:
            raise Died(f"--ref {self.args.ref} names no commit in {ROOT}")
        if sha != head:
            raise Died(
                f"--ref {self.args.ref} is {sha[:12]}, not {ROOT}'s HEAD {head[:12]}: publish"
                " exports a clean HEAD, so check the ref out and prove it there"
            )
        if self.dest.exists() and any(self.dest.iterdir()):
            raise Died(f"{self.dest} already holds something; name an empty --dest")
        self.source = sha
        exported = self.export()
        done = subprocess.run(
            ["git", "clone", "-q", "--no-checkout", str(self.export_dir), str(self.dest)],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise Died(f"git clone {self.export_dir}: {done.stderr.strip()}")
        self.git("checkout", "-q", "-B", "main", exported)
        for key, value in IDENTITY.items():
            self.git("config", f"user.{key.lower()}", value)
        if self.args.plant:
            path, old, new = PLANTS[self.args.plant]
            target = self.dest / path
            text = target.read_text()
            if text.count(old) != 1:
                raise Died(f"the plant {self.args.plant} found no single anchor in {path}")
            target.write_text(text.replace(old, new))
            self.git("add", "--", path)
            self.git("commit", "-q", "-m", f"plant: {self.args.plant}")
        self.step("clone", began, f"the export of {sha[:12]} at {self.dest}")

    def export(self) -> str:
        """`publish --to <dest>.export` of ROOT, logged as `export.log`; the export's commit."""
        began = time.monotonic()
        log = self.out_dir / "export.log"
        path = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
        with log.open("w") as sink:
            rc = subprocess.run(
                [sys.executable, "-P", "-c", EXPORT, "--to", str(self.export_dir)],
                cwd=ROOT,
                stdout=sink,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=child_env(PYTHONPATH=str(CODE), PATH=path),
                check=False,
            ).returncode
        if rc != 0:
            raise Died(f"publish --to {self.export_dir} exited {rc}: no export to clone ({log})")
        said = subprocess.run(
            ["git", "-C", str(self.export_dir), "rev-parse", "HEAD", "HEAD^{tree}"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        if len(said) != 2:
            raise Died(f"the export {self.export_dir} has no commit ({log})")
        self.step("export", began, f"tree {said[1]} of the source {self.source[:12]} (one census)")
        return said[0]

    def setup(self) -> None:
        """`./scripts/setup.sh` and the seed in the clone; anything but 0 is could-not-look."""
        rc, _, seconds = self.run_logged("setup", ["./scripts/setup.sh"])
        if rc != 0:
            raise Died(f"./scripts/setup.sh exited {rc} ({self.out_dir}/setup.log)")
        rc, _ = self.manage("seed", "seed")
        if rc != 0:
            raise Died(f"manage.py seed exited {rc} ({self.out_dir}/seed.log)")
        again, text, _ = self.run_logged("setup-again", ["./scripts/setup.sh"])
        reused = next((ln.strip() for ln in text.splitlines() if REUSED in ln), f"no `{REUSED}`")
        if again != 0:
            self.findings.append(
                f"setup.sh on the running stack exited {again}: {first_refusal(text)}"
            )
        out(f"   setup-again: exit {again} · {reused}")
        rc, text, _ = self.run_logged("sdk-version", [".venv/bin/python", "-c", SDK_VERSION])
        said = text.strip().splitlines()[-1:] if rc == 0 else []
        self.sdk = said[0] if said and re.fullmatch(ledger.PROOF_SDK, said[0]) else "-"
        out(f"   [{seconds:.1f}s] setup: exit 0 · seeded · sdk {self.sdk}")

    def declare(self) -> None:
        """The product shape declared by `manage.py declare` and committed through the hook."""
        began = time.monotonic()
        rc, text = self.manage("declare", "declare", NAMESPACE)
        if rc != 0:
            raise Died(f"manage.py declare {NAMESPACE} exited {rc}: {first_refusal(text)}")
        self.git("add", "--", "quality/local/rules.yaml", "scripts/local/template-base")
        rc, text, _ = self.run_logged(
            "declare-commit",
            ["git", "commit", "-q", "-m", f"{NAMESPACE}: the product declares its shape"],
        )
        if rc != 0:
            self.findings.append(f"the declaration's commit exited {rc}: {first_refusal(text)}")
            self.git("reset", "-q")
        self.step("declare", began, f"namespace {NAMESPACE}, by manage.py declare")

    def product(self) -> None:
        """The first app and its scaffolded noun, committed (a refusal is a finding)."""
        began = time.monotonic()
        rc, _ = self.manage("newapp", "newapp", APP)
        if rc != 0:
            raise Died(f"manage.py newapp {APP} exited {rc} ({self.out_dir}/newapp.log)")
        rc, text = self.manage("declare-again", "declare", NAMESPACE)
        if rc != 0 or SHAPE not in text:
            raise Died(
                f"manage.py declare after newapp exited {rc} ({self.out_dir}/declare-again.log)"
            )
        rc, _ = self.manage("scaffold-noun", "scaffold", "noun", APP, NOUN)
        if rc != 0:
            raise Died(f"scaffold noun {APP} {NOUN} exited {rc} ({self.out_dir}/scaffold-noun.log)")
        if self.args.plant == "sdk-bypass":
            with (self.dest / BYPASS).open("a", encoding="utf-8") as module:
                module.write(BYPASS_LINE)
        self.tidy("product")
        self.git("add", "--", *self.changed())
        rc, text, _ = self.run_logged(
            "commit-product", ["git", "commit", "-q", "-m", f"{NAMESPACE}: the product's first app"]
        )
        if rc != 0:
            self.findings.append(f"the product's first commit exited {rc}: {first_refusal(text)}")
            self.git("commit", "-q", "--no-verify", "-m", f"{NAMESPACE}: the refused first app")
        self.git("update-ref", BASE_REF, "HEAD")
        leaf = self.dest / f"apps/{APP}/migrations/max_migration.txt"
        self.base_leaf = leaf.read_text().strip() if leaf.is_file() else "zero"
        self.step(
            "product", began, f"apps/{APP} with {NOUN} scaffolded, committed through the hook"
        )

    def tidy(self, tag: str) -> None:
        """The client and the budgets brought up to the tree, as a builder's tidy brings them."""
        argv = ["./scripts/rung_tidy.sh", "--client", "--budgets"]
        rc, _, _ = self.run_logged(f"tidy-{tag}", argv)
        if rc != 0:
            raise Died(f"rung_tidy exited {rc} ({self.out_dir}/tidy-{tag}.log)")

    def feature(self, index: int, one: Feature) -> None:
        """One shape down the road: scaffold, commit, lane, rule 96, then the loop and the drive."""
        began = time.monotonic()
        got = self.measured[index]
        self.git("reset", "-q", "--hard", BASE_REF)
        self.git("clean", "-q", "-fd", "--", "apps", "frontend")
        rc, text = self.manage(f"scaffold-{one.tag}", "scaffold", *one.words)
        got.scaffolded = rc == 0
        named = next((ln for ln in text.splitlines() if ln.startswith("next:")), "next: (none)")
        if rc != 0:
            got.failures.append(
                f"scaffold {' '.join(one.words)} exited {rc}: {first_refusal(text)}"
            )
            self.step(f"feature {one.tag}", began, "; ".join(got.failures))
            self.findings += [f"{one.words[0]}: {f}" for f in got.failures]
            return
        self.tidy(one.tag)
        self.git("add", "--", *self.changed())
        rc, text, _ = self.run_logged(
            f"commit-{one.tag}", ["git", "commit", "-q", "-m", f"{NAMESPACE}: {one.subject}"]
        )
        if rc != 0:
            got.failures.append(f"its commit exited {rc}: {first_refusal(text)}")
        rc, text, _ = self.run_logged(
            f"lane-{one.tag}",
            [".venv/bin/python", "-m", "quality.djb.scope", "lane", "--base", BASE_REF,
             "--head", "HEAD"],
        )  # fmt: skip
        if rc != 0:
            got.failures.append(f"the lane picker exited {rc}")
        got.lane, got.touched, got.tax = read_lane(text)
        if got.lane != "loop":
            got.failures.append(f"lane {got.lane}, not loop")
        if any(app != one.app for app in got.touched):
            got.failures.append(f"touched {' '.join(got.touched)} beyond {one.app}")
        if got.tax != "0":
            got.failures.append(f"tax {got.tax} min, not 0")
        got.rule96 = self.rule_96(one.tag)
        if got.rule96 is None:
            got.failures.append("rule 96 could not be measured")
        elif got.rule96[0]:
            got.failures.append(f"rule 96: {got.rule96[0]} platform import(s) in a product app")
        built_on_sdk = got.rule96 is not None and not got.rule96[0]
        if (
            got.lane == "loop"
            and built_on_sdk
            and not any(f.startswith("its commit") for f in got.failures)
        ):
            self.road(one, got)
        verdict = "; ".join(got.failures) or "ok"
        self.step(f"feature {one.tag}", began, f"{one.words[0]} · {named} · lane={got.lane} "
                  f"tax={got.tax} drive={got.drive} — {verdict}")  # fmt: skip
        self.findings += [f"{one.words[0]}: {f}" for f in got.failures]

    def rule_96(self, tag: str) -> tuple[int, int] | None:
        """Rule 96 judged on the clone whatever its `enabled:` says: (findings, valves held)."""
        rc, text, _ = self.run_logged(f"rule96-{tag}", [".venv/bin/python", "-c", RULE_96])
        head = text.strip().splitlines()[:1] if rc == 0 else []
        found = re.fullmatch(r"(\d+) (\d+)", head[0]) if head else None
        return (int(found.group(1)), int(found.group(2))) if found else None

    def road(self, one: Feature, got: Measured) -> None:
        """`feature.sh <app> --loop --drive <Noun>` with the clone migrated and its stack up."""
        rc, _ = self.manage(f"migrate-{one.tag}", "migrate")
        if rc != 0:
            got.failures.append(f"manage.py migrate exited {rc}")
            return
        stack = Stack(self, one.tag)
        try:
            if not stack.up():
                got.failures.append(f"the stack did not answer /readyz ({self.out_dir})")
                return
            rc, text, _ = self.run_logged(
                f"feature-{one.tag}",
                ["./scripts/feature.sh", one.app, "--loop", "--drive", NOUN],
                DJB_LOOP_HERE=LOOP_REASON,
                DJB_LOOP_SCOPE_BASE=BASE_REF,
            )
        finally:
            stack.down()
            self.manage(f"unmigrate-{one.tag}", "migrate", one.app, self.base_leaf)
        gate = keep_gate_log(text, self.out_dir, one.tag)
        steps = read_road(text)
        loop = steps.get(GATE_STEP)
        got.loop_s = str(loop[1]) if loop else "-"
        drive = steps.get(f"./scripts/drive_doors.sh {NOUN}")
        got.drive = DRIVE_WORDS.get(drive[0], "unlooked") if drive else "-"
        if rc != 0:
            got.failures.append(road_refusal(rc, text, gate, one.tag))
        elif got.drive != "agree":
            got.failures.append(f"the drive said {got.drive}")

    def refusals(self) -> None:
        """The three refusals a product commit meets, and the one sanctioned stack edit."""
        from quality.djb.boundary import PLATFORM_REFUSAL, STACK_REFUSAL, TRAILER, VARIABLE

        began = time.monotonic()
        self.git("reset", "-q", "--hard", BASE_REF)
        self.git("clean", "-q", "-fd", "--", "apps", "frontend")
        self.append(FROZEN)
        rc, text, _ = self.run_logged("refuse-frozen", ["git", "commit", "-q", "-m", "frozen"])
        self.expect("frozen", rc == 1 and PLATFORM_REFUSAL.format(path=FROZEN) in text)
        self.git("reset", "-q", "--hard", BASE_REF)
        self.append(STACKED)
        rc, text, _ = self.run_logged("refuse-stack", ["git", "commit", "-q", "-m", "stack"])
        self.expect("stack", rc == 1 and STACK_REFUSAL.format(path=STACKED) in text)
        rc, _, _ = self.run_logged(
            "sanction-stack", ["git", "commit", "-q", "-m", "stack"], **{VARIABLE: SANCTION}
        )
        trailers = self.git("log", "-1", "--format=%(trailers)") if rc == 0 else ""
        if rc == 0 and f"{TRAILER}: {SANCTION}" in trailers:
            self.sanctioned = 1
        else:
            self.findings.append(
                f"the sanctioned {STACKED} commit exited {rc} or carried no trailer"
            )
        self.git("reset", "-q", "--hard", BASE_REF)
        (self.dest / AROUND).write_text("")
        self.git("add", "--", AROUND)
        self.git("commit", "-q", "--no-verify", "-m", f"{NAMESPACE}: an edit around the hook")
        rc, text, _ = self.run_logged("fast-around", ["./scripts/check.sh", "--fast"])
        self.expect("around", rc == 1 and re.search(rf"x rule 95: {re.escape(AROUND)}", text))
        self.git("reset", "-q", "--hard", BASE_REF)
        self.step("refusals", began, f"refused={self.refused} sanctioned={self.sanctioned}")

    def read_reference(self) -> None:
        """The clone's reference page count, and each feature's shape named on a page."""
        pages = (
            sorted((self.dest / REFERENCE).rglob("*.md"))
            if (self.dest / REFERENCE).is_dir()
            else []
        )
        if not pages:
            out(f"   reference: {REFERENCE}/ absent on this tree — reference=-")
            return
        self.reference = str(len(pages))
        text = "\n".join(page.read_text(errors="replace") for page in pages)
        for one in FEATURES:
            if not named_on_a_page(one.words[0], text):
                self.findings.append(f"{REFERENCE}/ names no `scaffold {one.words[0]}` on any page")
        out(f"   reference: {self.reference} page(s) under {REFERENCE}/")

    def append(self, path: str) -> None:
        with (self.dest / path).open("a") as handle:
            handle.write(f"# {NAMESPACE}\n")
        self.git("add", "--", path)

    def expect(self, which: str, held: object) -> None:
        if held:
            self.refused += 1
        else:
            self.findings.append(f"the {which} refusal did not come as written")

    def record(self, rc: int) -> str:
        """The record line, written to `<out>/proof_from_zero.txt` and returned."""
        if not self.source:
            self.source = "0" * 40
        if not self.tree:
            self.tree = "0" * 40
        judged = [m.rule96 for m in self.measured if m.rule96 is not None]
        rule96 = "-" if not judged else ("red" if any(k for k, _ in judged) else "green")
        valves = str(max(v for _, v in judged)) if judged else "-"
        joined = [
            ledger.ci_stamp(int(time.time())),
            self.source,
            self.tree,
            str(len(FEATURES)),
            ",".join(m.lane for m in self.measured),
            ",".join(m.tax for m in self.measured),
            ",".join(str(len(m.touched)) if m.lane != "-" else "-" for m in self.measured),
            ",".join(m.loop_s for m in self.measured),
            str(self.refused),
            str(self.sanctioned),
            self.sdk,
            rule96,
            valves,
            str(sum(m.scaffolded for m in self.measured)),
            ",".join(m.drive for m in self.measured),
            self.reference,
            str(rc),
            str(self.args.run),
            self.args.where,
        ]
        line = ledger.proof_line(joined)
        (self.out_dir / ledger.PROOF_RECORD).write_text(line + "\n")
        return line

    def run(self) -> int:
        """Every step in order; the record is written whatever happened."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        rc = 0
        try:
            self.clone()
            self.tree = self.git("rev-parse", "HEAD^{tree}")
            self.setup()
            self.declare()
            self.product()
            for index, one in enumerate(FEATURES):
                self.feature(index, one)
            self.refusals()
            self.read_reference()
            rc = 1 if self.findings else 0
        except Died as died:
            out(f"!! COULD NOT LOOK: {died}")
            rc = 2
        line = self.record(rc)
        for finding in self.findings:
            out(f"RED: {finding}")
        out(line)
        out(
            f"left: the clone {self.dest}, the export {self.export_dir} and the clone's database"
            f" for the reap; logs in {self.out_dir}"
        )
        return rc


class Stack:
    """The clone's web and worker processes for one drive, each in its own process group."""

    def __init__(self, proof: Proof, tag: str) -> None:
        self.proof = proof
        self.tag = tag
        self.children: list[subprocess.Popen[bytes]] = []

    def up(self) -> bool:
        """Both started, then True once `/readyz` answers 200 inside the ready window."""
        rc, text, _ = self.proof.run_logged(
            f"port-{self.tag}", ["./scripts/serve.sh", "--print-port"]
        )
        port = text.strip().splitlines()[0] if rc == 0 and text.strip() else ""
        if not port.isdigit():
            return False
        for script in ("./scripts/serve.sh", "./scripts/worker.sh"):
            sink = (self.proof.out_dir / f"{Path(script).stem}-{self.tag}.log").open("w")
            self.children.append(
                subprocess.Popen(
                    [script],
                    cwd=self.proof.dest,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=child_env(),
                    start_new_session=True,
                )
            )
        deadline = time.monotonic() + READY_SECONDS
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=5) as said:
                    if said.status == 200:
                        return True
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(1)
        return False

    def down(self) -> None:
        """Each child's whole process group ended: TERM, then KILL after twenty seconds."""
        for child in self.children:
            for sent in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(child.pid, sent)
                except ProcessLookupError:
                    break
                try:
                    child.wait(timeout=20)
                    break
                except subprocess.TimeoutExpired:
                    continue


def first_refusal(text: str) -> str:
    """The first `!!` or `x ` line a hook printed, or its last line."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hit = next((ln for ln in lines if ln.startswith(("!!", "x "))), "")
    return (hit or (lines[-1] if lines else "no output"))[:240]


GATE_STEP = "./scripts/check.sh --loop"


def keep_gate_log(road: str, out_dir: Path, tag: str) -> str:
    """The gate log `feature.sh` printed, copied to `<out>/gate-<tag>.log`; its text, or empty."""
    command = ""
    for line in road.splitlines():
        hit = re.match(r"\s+exit \d+ \(\d+s\) · log (\S+)", line)
        if line.startswith("- "):
            command = line[2:].strip()
        elif hit and command == GATE_STEP:
            try:
                text = Path(hit.group(1)).read_text(errors="replace")
            except OSError as exc:
                text = f"the gate log {hit.group(1)} could not be read: {exc}\n"
            (out_dir / f"gate-{tag}.log").write_text(text)
            return text
    return ""


def road_refusal(rc: int, road: str, gate: str, tag: str) -> str:
    """Why `feature.sh` stopped; a loop that could not look names its member, case and why."""
    if rc != 2 or read_road(road).get(GATE_STEP, (0, 0))[0] != 2:
        return f"feature.sh exited {rc}: {first_refusal(road)}"
    member = re.search(r"^!! COULD NOT LOOK: (.+)$", gate, flags=re.MULTILINE)
    case = re.search(r"COULD NOT LOOK (\S+?::.+?): COULD NOT LOOK — (.+)$", gate, re.MULTILINE)
    named = member.group(1).strip() if member else "a member the gate log does not name"
    if case is None:
        return f"--loop could not look — {named} (gate-{tag}.log names no case)"
    why = re.split(r"(?<=\.)\s", case.group(2).strip(), maxsplit=1)[0][:240]
    return f"--loop could not look — {named}: {case.group(1)} — {why}"


def read_lane(text: str) -> tuple[str, list[str], str]:
    """`scope lane`'s word, its `scope touched:` apps and its tax minutes (`-` when absent)."""
    lines = text.splitlines()
    word = lines[0].strip() if lines and lines[0].strip() in ("docs", "loop", "full") else "-"
    touched: list[str] = []
    tax = "-"
    for line in lines:
        hit = re.match(r"\s+scope\s+touched:\s*(.*)$", line)
        if hit and hit.group(1).strip() != "-":
            touched = hit.group(1).split()
        hit = re.match(r"\s+tax: (\S+) min", line)
        if hit:
            tax = hit.group(1)
    return word, touched, tax


def named_on_a_page(shape: str, text: str) -> bool:
    """`scaffold <shape>` in the reference's prose, or `<shape>` opening a shapes-table line."""
    word = re.escape(shape)
    return bool(re.search(rf"scaffold {word}\b|^{word}\s", text, flags=re.MULTILINE))


def read_road(text: str) -> dict[str, tuple[int, int]]:
    """`feature.sh`'s steps as {command: (exit, seconds)}, from its `- cmd` / `exit N (Ns)`."""
    steps: dict[str, tuple[int, int]] = {}
    command = ""
    for line in text.splitlines():
        if line.startswith("- "):
            command = line[2:].strip()
            continue
        hit = re.match(r"\s+exit (\d+) \((\d+)s\)", line)
        if hit and command:
            steps[command] = (int(hit.group(1)), int(hit.group(2)))
            command = ""
    return steps


def parse(argv: Sequence[str]) -> argparse.Namespace:
    """The command line: what to prove, where, and how the record names its run."""
    parser = argparse.ArgumentParser(prog="scripts/proof_from_zero.sh", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the steps and the shapes")
    parser.add_argument("--ref", default="HEAD", help="the commit under proof (default HEAD)")
    parser.add_argument("--dest", default="", help="an empty directory for the clone")
    parser.add_argument("--out", default="", help="where the record and the logs go")
    parser.add_argument("--plant", choices=sorted(PLANTS), default="", help="a planted regression")
    parser.add_argument("--run", default="0", help="the CI run id the record names (0: none)")
    parser.add_argument("--where", choices=("ci", "local"), default="local")
    parser.add_argument("--inputs", action="store_true", help="print what the proof drives")
    args = parser.parse_args(list(argv))
    scratch = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "djb-proof"
    stamp = time.strftime("%Y%m%dT%H%M%S")
    args.dest = args.dest or str(scratch / f"clone-{stamp}")
    args.out = args.out or str(scratch / f"record-{stamp}")
    return args


def dry_run() -> int:
    """The steps and the three shapes, and nothing run."""
    out("proof from zero — the steps, in order:")
    for line in STEPS:
        out(f"  {line}")
    out("the shapes:")
    for one in FEATURES:
        out(f"  manage.py scaffold {' '.join(one.words)}  ({one.app}: {one.subject})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """`proof_from_zero [--dry-run] [--ref R] [--dest D] [--out O] [--plant P]`: 0 · 1 · 2."""
    drop_own_path()
    try:
        refuse_if_piped()
        args = parse(sys.argv[1:] if argv is None else argv)
        if args.inputs:
            out("\n".join(INPUTS))
            return 0
        from quality.engine.rules import declared_namespace

        if declared_namespace() is not None:
            print(f"!! REFUSED: {PRODUCT_TREE}", file=sys.stderr)
            return 2
        if args.dry_run:
            return dry_run()
        if shutil.which("git") is None:
            raise Died("no git on PATH")
        return Proof(args).run()
    except CouldNotLook as died:
        print(f"!! COULD NOT LOOK: {died}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
