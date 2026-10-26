"""The `pytest-x2` unit: temporal census, partition, two seeded passes, the grants pass."""

# Invariant: stdlib only; every pass runs under ONE seed and ONE slot's `-n` (ADR gate-1).
# does-not-cover: the pass-1 heartbeat and its measured nominal — the typed nominal is printed.
# does-not-cover: the three other shell members of the unit by name — this body runs them all.

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from quality.could_not_look import tool_said
from quality.djb import hold
from quality.djb.legs import gate_tests
from quality.djb.legs._run import CAUSE, LIBRARIES, could_not_look, say
from quality.djb.registry import Ctx, Leg

DECIDE = ("uv", "run", "python", "-m", "quality.partition", "decide")
BANK = ("uv", "run", "python", "-m", "quality.partition", "bank")
PATHS = gate_tests.PATHS
ARGV = (DECIDE, BANK, PATHS)
TEST_SH = "./scripts/test.sh"
SWEEP = "./scripts/sweep.sh"
TEMPORAL_SWEEP = "scripts/temporal_sweep.sh"
DURATIONS = "scripts/pytest_durations.json"
GRANTS_ROLE = "djb_grants_pass"
GRANTS_SECRET = "djb-grants-pass"  # noqa: S105 — the grants role password of the throwaway gate database  # pragma: allowlist secret
#: What a pass that never came up looks like in its own output.
HARNESS = (
    (
        re.compile(
            r"no tests ran|collected 0 items|INTERNALERROR|ERROR collecting|"
            r"error(s)? during collection|ERROR: usage",
            re.IGNORECASE,
        ),
        "zero tests ran, or collection failed",
    ),
    (
        re.compile(r"WorkflowEnvironment|start_time_skipping|temporal-test-server|BindException"),
        "Temporal test-server / WorkflowEnvironment traces",
    ),
)
_FAILURES = re.compile(r"^FAILED |[0-9]+ (failed|error)", re.MULTILINE)
_SUMMARY = re.compile(r"^=+ short test summary info =+$")
_SECTION = re.compile(r"^___+ .+ ___+$")

#: The line a product tree prints instead of deciding the platform partition.
ON_A_PRODUCT = (
    "pytest-x2: the platform partition proof is the template's — not a product's to pay for;"
    " the template's CI vouches"
)
_APPS_FRAME = re.compile(r"^apps/[^ :]+\.py:[0-9]+")
_FILE_FRAME = re.compile(r'File "[^"]*/apps/([^"]+\.py)", line ([0-9]+)')
_DENIED = re.compile(r"permission denied for table ([A-Za-z0-9_]+)")

#: Makes the least-privilege role and its template database, or drops the template.
GRANTS_DB = """import importlib.util
import os
import subprocess
import sys

import django

django.setup()
import psycopg
from django.conf import settings
from psycopg import sql

db = settings.DATABASES["default"]
admin = dict(
    user=db["USER"],
    password=db["PASSWORD"],
    host=db["HOST"] or "127.0.0.1",
    port=db["PORT"] or 5432,
)
action = os.environ["DJB_GRANTS_ACTION"]
role = os.environ["DJB_GRANTS_ROLE"]
template = os.environ.get("DJB_GRANTS_TEMPLATE") or f"{db['NAME']}_grants"


def say(line: str) -> None:
    print(line, flush=True)


try:
    with psycopg.connect(dbname="postgres", autocommit=True, **admin) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(template))
        )
        if action == "teardown":
            say(f"dropped={template}")
            sys.exit(0)
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            sql.SQL(verb + " ROLE {} LOGIN CREATEDB NOSUPERUSER PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(os.environ["DJB_GRANTS_SECRET"])
            )
        )
        source = os.environ.get("DJB_GRANTS_SOURCE", "")
        if source:
            conn.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(template), sql.Identifier(source)
                )
            )
        else:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(template)))
    if not source:
        env = dict(os.environ, DATABASE_NAME=template)
        done = subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            env=env, capture_output=True, text=True, check=False,
        )
        if done.returncode != 0:
            from quality.could_not_look import tool_said

            said = tool_said(done.stdout + done.stderr)
            say(f"the grants template would not migrate (exit {done.returncode}){said}")
            sys.exit(2)
    spec = importlib.util.spec_from_file_location("grants_sql", "deploy/grants.sql.py")
    grants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grants)
    tables = grants.append_only_tables()
    if not tables:
        say("grants.sql.py found no append-only table — there is nothing for this pass to wear")
        sys.exit(2)
    with psycopg.connect(dbname=template, autocommit=True, **admin) as conn:
        conn.execute(grants.render(role=role, tables=tables))
        ident = sql.Identifier(role)
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        for (name,) in rows:
            if name not in tables:
                conn.execute(
                    sql.SQL("ALTER TABLE {} OWNER TO {}").format(sql.Identifier(name), ident)
                )
        conn.execute(sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(ident))
        conn.execute(sql.SQL("GRANT TRUNCATE ON ALL TABLES IN SCHEMA public TO {}").format(ident))
        conn.execute(sql.SQL("GRANT UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}").format(ident))
        conn.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(sql.Identifier(template), ident)
        )
    say(f"template={template} ledgers={len(tables)}:{','.join(tables)} from={source or 'migrate'}")
except psycopg.Error as exc:
    say(f"postgres refused: {str(exc).strip().splitlines()[0]}")
    sys.exit(2)
"""


@dataclass(frozen=True)
class Decision:
    """The partition's answer: skip or measure, its key, the targets, whether it may bank."""

    mode: str
    key: str
    targets: tuple[str, ...]
    bankable: bool


@dataclass(frozen=True)
class Run:
    """What the mode handed this unit: shard, passes, `--store-durations`, `--pr`, `--bank`."""

    shard: tuple[int, int] | None
    passes: str
    store: bool
    pr: bool
    bank: bool
    product: bool = False

    @classmethod
    def of(cls, env: Mapping[str, str]) -> Run:
        """Read from the environment the mode sets (`GATE_SHARD_K`/`_N`, `GATE_PASSES`, …)."""
        k, n = env.get("GATE_SHARD_K", ""), env.get("GATE_SHARD_N", "")
        shard = (int(k), int(n)) if k.isdigit() and n.isdigit() else None
        return cls(
            shard,
            env.get("GATE_PASSES", ""),
            bool(env.get("GATE_STORE_DURATIONS")),
            bool(env.get("GATE_PR")),
            bool(env.get("GATE_BANK")),
        )

    @property
    def run_word(self) -> str:
        """`both passes run` or `the one pass runs` (`GATE_PASSES_RUN`)."""
        return "the one pass runs" if self.passes == "1" or self.product else "both passes run"

    @property
    def carry_word(self) -> str:
        """`both passes carry` or `the one pass carries` (`GATE_PASSES_CARRY`)."""
        return "the one pass carries" if self.passes == "1" else "both passes carry"


def _flush() -> None:
    sys.stdout.flush()
    sys.stderr.flush()


def _env(ctx: Ctx, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    return {**ctx.env, **(extra or {})}


def _captured(
    ctx: Ctx, argv: Sequence[str], env: Mapping[str, str] | None = None
) -> tuple[int, str]:
    """`argv` with both streams to one file; its exit and its text, nothing printed."""
    _flush()
    with tempfile.TemporaryFile() as out:
        try:
            rc = subprocess.run(
                list(argv), cwd=ctx.root, env=_env(ctx, env), stdout=out, stderr=out
            ).returncode
        except OSError as exc:
            return 2, f"!! {argv[0]} could not be started: {exc}\n"
        out.seek(0)
        return rc, out.read().decode(errors="replace")


def _streamed(ctx: Ctx, argv: Sequence[str], env: Mapping[str, str] | None = None) -> int:
    """`argv` with the terminal's streams; its exit."""
    _flush()
    try:
        return subprocess.run(list(argv), cwd=ctx.root, env=_env(ctx, env)).returncode
    except OSError as exc:
        say(f"!! {argv[0]} could not be started: {exc}")
        return 2


def _bash(ctx: Ctx, script: str, env: Mapping[str, str] | None = None) -> tuple[int, str]:
    """`script` over the gate's libraries; its exit and its stdout, stderr passed on."""
    prelude = "".join(f". {lib} || exit 2\n" for lib in LIBRARIES)
    _flush()
    try:
        done = subprocess.run(
            ["bash", "-c", f"{prelude}gate_refuse_reset\nset +e\n{script}"],
            cwd=ctx.root,
            env=_env(ctx, env),
            stdout=subprocess.PIPE,
        )
    except OSError as exc:
        return 2, f"bash could not be started: {exc}"
    return done.returncode, done.stdout.decode(errors="replace")


def finding(*lines: str) -> int:
    """A finding's banner (`gate_finding`); 1."""
    say(f"!! {lines[0]}", *(f"   {line}" for line in lines[1:]))
    return 1


def temporal_census(ctx: Ctx, phase: str) -> tuple[int, list[str], list[str]]:
    """`temporal_sweep.sh`'s census: exit, every pid seen, every ORPHAN pid — each once."""
    if not os.access(ctx.root / TEMPORAL_SWEEP, os.X_OK):
        say(
            f"!! THE TEMPORAL CENSUS CANNOT BE TAKEN — {TEMPORAL_SWEEP} is",
            "   missing or not executable. Nothing here is a finding and nothing here is",
            "   a pass: this gate has no way to know whether the suite leaves a test",
            "   server behind, which is the whole point of the leg.",
        )
        return 2, [], []
    rc, text = _captured(ctx, [TEMPORAL_SWEEP])
    print(f"  census ({phase}):", flush=True)
    sys.stdout.write(text)
    if rc != 0:
        say(
            f"!! THE TEMPORAL CENSUS FAILED ({phase}, exit {rc}) — the instrument itself is",
            "   broken, and a broken instrument reporting a clean floor is the class this",
            "   leg exists to refuse.",
        )
        return 2, [], []
    seen: list[str] = []
    orphans: list[str] = []
    for line in text.splitlines():
        words = line.split()
        if len(words) < 3:
            continue
        if words[0] in ("ORPHAN", "LIVE", "REFUSED") and words[2] not in seen:
            seen.append(words[2])
        if words[0] == "ORPHAN" and words[2] not in orphans:
            orphans.append(words[2])
    return 0, seen, orphans


def new_orphans(before: Sequence[str], orphans: Sequence[str]) -> int:
    """The census after the suite: an orphan in no state before it is exit 1."""
    fresh = [pid for pid in orphans if pid not in before]
    if fresh:
        say(
            "!! THE SUITE LEFT A TEMPORAL TEST SERVER BEHIND.",
            "   Orphaned after the suite, and not on this machine in any state before it:",
            *(f"     pid {pid}" for pid in fresh),
            "   An orphan listens on nothing, is invisible to a port probe, and lives until",
            "   the machine is rebooted — and it holds the port a later pass needs.",
            "   Stop it with: ./scripts/temporal_sweep.sh --sweep",
        )
        return 1
    print("  no new orphan: this suite left no test server behind", flush=True)
    return 0


def read_decision(path: Path) -> Decision | None:
    """The decision file `quality.partition decide --out` wrote, or None when unreadable."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        paths = doc["paths"]
        targets = tuple(paths) if isinstance(paths, list) else tuple(str(paths).split())
        return Decision(str(doc["mode"]), str(doc["key"]), targets, doc["bankable"] is True)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def product_pass(ctx: Ctx) -> tuple[int, Decision | None] | None:
    """A product tree's own apps as one pass, never the partition; None on the template."""
    if gate_tests.product_of(ctx.root) is None:
        return None
    print(f"  {ON_A_PRODUCT}", flush=True)
    try:
        apps = gate_tests.product_apps(ctx.root, lambda argv: _captured(ctx, argv))
    except gate_tests.Unnamed as exc:
        sys.stdout.write(exc.text)
        say(
            f"!! THE PARTITION COULD NOT NAME THIS PRODUCT'S APPS (exit {exc.rc})."
            " Nothing was judged."
        )
        return 2, None
    return 0, Decision("product", "", apps, False)


def partition(ctx: Ctx, run: Run) -> tuple[int, Decision | None]:
    """The platform partition's decision, re-read for `--pr`, a shard or `--store-durations`."""
    if (product := product_pass(ctx)) is not None:
        return product
    with tempfile.NamedTemporaryFile(prefix="djb-partition-decision.", delete=False) as handle:
        out = Path(handle.name)
    try:
        rc = _streamed(ctx, [*DECIDE, "--out", str(out)])
        if rc == 1:
            return finding(
                "THE PARTITION FOUND SOMETHING (exit 1) — read the lines above.",
                "A negative that fired, or a discovery walk no digest section claims.",
            ), None
        if rc != 0:
            say(
                f"!! THE PARTITION'S ENFORCEMENT IS BROKEN (exit {rc}).",
                "   A canary that does not fire is exit 2, not a pass, and a partition that",
                "   cannot prove its own key moves may not decide whether to skip the suite.",
                "   Nothing here is a finding about your change.",
            )
            return 2, None
        decision = read_decision(out)
    finally:
        out.unlink(missing_ok=True)
    if decision is None or not decision.mode:
        say(
            "!! THE PARTITION'S DECISION COULD NOT BE READ BACK (exit 2).",
            "   It exited 0 and wrote a decision this gate cannot parse, which means the",
            "   gate does not know what it is about to run.",
        )
        return 2, None
    mode, targets = decision.mode, decision.targets
    if run.pr:
        if mode == "skip":
            print(
                f"  --pr IGNORES THE BANKED PARTITION ROW (key {decision.key}): both passes\n"
                "  collect the whole suite and deselect from it, because the scope's always-on\n"
                "  floors are asserted over the whole collection. A path-narrowed pass under a\n"
                "  scope is exit 2 by construction, never a smaller run.",
                flush=True,
            )
        mode, targets = "measure", tuple(ctx.env.get("GATE_PR_PYTEST_ARGS", "").split())
    if run.shard is not None or run.store:
        if mode == "skip":
            lead = f"shard {run.shard[0]}/{run.shard[1]} " if run.shard else ""
            print(
                f"  {lead}IGNORES THE BANKED PARTITION ROW (key {decision.key}):\n"
                "  the split is over a collection, and a collection one runner's ledger has\n"
                "  already narrowed is not the one the other shards are splitting.",
                flush=True,
            )
        mode = "measure"
        if not run.pr:
            targets = ()
    return 0, Decision(mode, decision.key, targets, decision.bankable)


def seed(env: Mapping[str, str]) -> int | None:
    """The run's one seed: `DJB_GATE_PYTEST_SEED` when typed, else minted; None refuses."""
    typed = env.get("DJB_GATE_PYTEST_SEED")
    if typed:
        if not typed.isdigit():
            say(
                "!! DJB_GATE_PYTEST_SEED is set and is not a non-negative integer.",
                f"   got: {typed}",
                "   A seed this gate cannot parse is never replaced by a minted one: every",
                "   shard of one run has to split the SAME collection order, and a silent",
                "   fallback is how two shards come to split two different suites.",
                "   Nothing was judged.",
            )
            return None
        print(f"  seed: {typed} (typed: DJB_GATE_PYTEST_SEED)", flush=True)
        return int(typed)
    minted = random.getrandbits(30)
    print(f"  seed: {minted} (minted)", flush=True)
    return minted


def durations_path(root: Path, env: Mapping[str, str]) -> str | None:
    """The durations file pytest-split reads, refused outside the rootdir or through `..`."""
    want = env.get("DJB_GATE_DURATIONS_PATH") or DURATIONS
    real_root = str(root.resolve())
    real = want if want.startswith("/") else f"{real_root}/{want}"
    if "/../" in f"/{real}/":
        say(
            f"!! --durations-path '{want}' contains a '..' segment.",
            f"   rootdir:  {real_root}",
            f"   resolved: {real}",
            "   A path that climbs out of the rootdir is refused whether or not it",
            "   lands back inside it: see the collapse below. Nothing was judged.",
        )
        return None
    if not real.startswith(f"{real_root}/"):
        say(
            f"!! --durations-path '{want}' resolves OUTSIDE pytest's rootdir.",
            f"   rootdir:  {real_root}",
            f"   resolved: {real}",
            "   pytest-split reads that file and then SILENTLY COLLAPSES the partition:",
            "   measured, a 3-way split of 3822 items came back as 3, 3 and 1 items, with",
            "   no warning and exit 0. A shard that judged three tests is not a smaller",
            "   run, it is a green that means nothing. Nothing was judged.",
        )
        return None
    return want


def split_args(ctx: Ctx, run: Run) -> list[str] | None:
    """`--splits N --group k` (or `--store-durations`) with the durations path; None refuses."""
    if run.shard is None and not run.store:
        return []
    durations = durations_path(ctx.root, ctx.env)
    if durations is None:
        return None
    args: list[str] = []
    if run.shard is not None:
        k, n = run.shard
        if n == 1:
            print("  shard 1/1: the WHOLE unit — no split flags, and therefore no plugin needed.")
        else:
            if (ctx.root / durations).is_file():
                print(f"  durations: {durations} — regenerate with")
                print("             ./scripts/check.sh --leg pytest-x2 --store-durations")
            else:
                print("  durations: none — unbalanced split (the groups are chunked by count;")
                print("             every collected test is still in exactly one of them)")
            args = ["--splits", str(n), "--group", str(k), "--durations-path", durations]
            print(f"  shard {k}/{n}: {run.carry_word} {' '.join(args)}")
        if run.passes == "1":
            print(
                "  passes 1: pass 2 is NOT run here — the leak proof is the acceptance box's "
                "(ADR gate-1)"
            )
    else:
        args = ["--store-durations", "--durations-path", durations]
        print(f"  --store-durations: this run REWRITES {durations}. It is a")
        print("  MEASUREMENT and not a verdict — pass 2 is not run and nothing is banked.")
    sys.stdout.flush()
    return args


def counts_short(counts_dir: str, workers: int) -> int:
    """2 when fewer collectors reported than were asked for (`loop_counts_refuse_if_short`)."""
    if not counts_dir:
        return 0
    files = sorted(str(p) for p in Path(counts_dir).rglob("*") if p.is_file())
    expected = workers
    if files:
        try:
            for line in Path(files[0]).read_text(encoding="utf-8").splitlines():
                if line.startswith("workers="):
                    value = line.split("=", 1)[1]
                    if value.isdigit() and int(value) >= 1:
                        expected = int(value)
                    break
        except OSError:
            pass
    if expected <= 0 or len(files) >= expected:
        return 0
    say(
        f"!! {len(files)} of {expected} collectors reported — a collector died and the suite that "
        f"ran is not the suite that was asked for; nothing is judged",
        "   Every collector performs its own FULL collection and writes its counts, so",
        "   a missing file is a collector that never got to the end of collecting.",
        "   pytest can still exit 0 from that state (it runs what the survivors hold,",
        "   and 'no tests ran' is not a failure), which is why this is a refusal here",
        "   and not a note beside a green verdict. No verdict is banked.",
        "!! the two pytest passes could not be RECONCILED — see above.",
        "   No verdict row, no partition row: a run that cannot say how much of the",
        "   suite collected has nothing to bank.",
    )
    return 2


def summary_of(text: str, cap: int = 20) -> list[str]:
    """The short-summary section's lines, else the FAILED/ERROR lines; at most `cap`."""
    section: list[str] = []
    fallback: list[str] = []
    inside = seen = False
    for line in text.splitlines():
        if _SUMMARY.match(line):
            inside = seen = True
            continue
        if inside and line.startswith("="):
            inside = False
        if inside:
            if len(section) < cap:
                section.append(f"     {line}")
            continue
        if not seen and re.match(r"^(FAILED|ERROR) [^ ]", line) and len(fallback) < cap:
            fallback.append(f"     {line}")
    return section if seen else fallback


def failed_in_summary(text: str) -> list[str]:
    """The FAILED/ERROR lines of the short-summary section, indented for the closing list."""
    found: list[str] = []
    inside = False
    for line in text.splitlines():
        if _SUMMARY.match(line):
            inside = True
            continue
        if inside and line.startswith("="):
            inside = False
        if inside and re.match(r"^(FAILED|ERROR) ", line):
            found.append(f"     {line}")
    return found


def pass2_verdict(text: str, seed_: int, workers: int) -> list[str]:
    """What a red pass 2 means: the harness, an inherited state, or nothing nameable."""
    harness = [why for pattern, why in HARNESS if pattern.search(text)]
    failures = bool(_FAILURES.search(text))
    lines = [""]
    if harness:
        lines += [
            "!! PASS 2 DID NOT COME UP — no inference about idempotency is possible.",
            f"   This leg saw: {'; '.join(harness)}.",
            "   A harness that does not come up produces failures of its own, so nothing",
            "   here says anything about what pass 1 left behind. Fix the harness, then",
            f"   re-run: ./scripts/test.sh -n {workers} --randomly-seed={seed_}",
        ]
        if failures:
            lines += [
                "   (Tests are reported failed or errored above. This leg does NOT read them as",
                "    state inherited from pass 1 — it cannot tell those apart from the harness.)",
            ]
    elif failures:
        lines += [
            "!! A TEST THAT PASSED IN PASS 1 FAILED IN PASS 2 UNDER THE SAME SEED.",
            f"   Both passes ran seed {seed_} at the same worker count: the seed fixes the "
            "collection order; under xdist's default --dist load the worker assignment is "
            "timing-dependent.",
            "   So the ORDER is not the difference; which worker ran which test may have been.",
            "   THE INFERENCE — and it is an inference, not a measurement — is that pass 1",
            "   left state behind. Clean on the way IN, not on the way out, and not by",
            "   resetting the database underneath it.",
        ]
        summary = summary_of(text)
        if summary:
            lines += ["   What pass 2 reported:", *summary, ""]
    else:
        lines += [
            "!! PASS 2 FAILED AND THIS LEG CANNOT TELL WHY.",
            "   It found no failed-test summary and no harness or collection fault in pass 2's",
            "   output, so it is not going to name a cause. Read the output above.",
            f"   Both passes ran seed {seed_} at the same worker count.",
        ]
    return lines


def _targets(args: Sequence[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def passes(
    ctx: Ctx, run: Run, workers: int, seed_: int, args: Sequence[str], counts_dir: str
) -> int:
    """Pass 1 streamed, then pass 2 under the same seed and `-n`; 0/1/2."""
    argv = [TEST_SH, "-n", str(workers), f"--randomly-seed={seed_}", *args]
    rc = _streamed(ctx, argv)
    if run.product and rc == 5:
        print(
            f"  pytest-x2: {' '.join(_targets(args))} has no tests yet — nothing to run", flush=True
        )
        return 0
    if rc != 0:
        if counts_short(counts_dir, workers):
            return 2
        if rc in (3, 4, 5):
            shard = ""
            if run.shard is not None:
                shard = (
                    f"   THIS RUN IS SHARD {run.shard[0]}/{run.shard[1]}. A shard that collected "
                    "nothing has judged\n   nothing: it is not a green part and it is not a red "
                    "suite. Check that N is\n   not larger than the collection, and that the scope "
                    "this shard split is the\n   one its siblings split."
                )
            say(
                f"!! PASS 1 DID NOT RUN THE SUITE (pytest exit {rc}).",
                "   3 internal error · 4 usage error · 5 nothing was collected.",
                *([shard] if shard else []),
                "   Nothing was judged about this tree, which is neither a finding nor a pass.",
            )
            return 2
        say("!! pass 1 is red — the suite fails on its own, before idempotency is in question.")
        return 1
    if counts_short(counts_dir, workers):
        return 2
    print(f"  pytest pass 1: green (seed {seed_})", flush=True)
    if run.store:
        print("  pass 2 NOT run — --store-durations is a measurement, not a verdict.")
        print(f"  {DURATIONS} has been rewritten from pass 1's timings.", flush=True)
        return 0
    if run.product:
        print("  pytest pass 2 NOT run — a product pass is one pass", flush=True)
        return 0
    if run.passes == "1":
        print(
            "  pytest pass 2 NOT run — --passes 1: the leak proof is the acceptance box's "
            "(ADR gate-1)",
            flush=True,
        )
        return 0
    if counts_dir:
        for path in Path(counts_dir).rglob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
    print("  pytest pass 2 running (output is captured and printed whole when it ends)...")
    rc, text = _captured(ctx, argv)
    sys.stdout.write(text)
    sys.stdout.flush()
    if counts_short(counts_dir, workers):
        return 2
    if rc != 0:
        say(*pass2_verdict(text, seed_, workers))
        return 1
    print(f"  pytest pass 2: green (seed {seed_})", flush=True)
    return 0


def grants_judge(text: str, ledgers: Sequence[str]) -> list[tuple[str, str, str]]:
    """Each refused ledger write as `(PROD|TEST, test, where)`, sorted bytewise."""
    tables = set(ledgers)
    ledger: dict[str, str] = {}
    where: dict[str, str] = {}
    by: dict[str, str] = {}
    sect = frame = caller = ""

    def app(f: str) -> str:
        parts = f.split("/")
        return parts[1] if len(parts) > 1 else ""

    def is_test(f: str) -> bool:
        return "/tests/" in f or "conftest.py:" in f or bool(re.match(r"^apps/test_[^/]*:", f))

    for line in text.splitlines():
        if _SECTION.match(line):
            sect, frame, caller = re.sub(r"^_+ | _+$", "", line), "", ""
            continue
        hit = _APPS_FRAME.match(line)
        found = f"apps/{m.group(1)}:{m.group(2)}" if (m := _FILE_FRAME.search(line)) else ""
        if hit or found:
            f = hit.group(0) if hit else found
            if frame and not is_test(frame) and app(frame) != app(f):
                caller = frame
            frame = f
            continue
        denied = _DENIED.search(line)
        if denied and denied.group(1) in tables:
            ledger[sect] = denied.group(1)
            if frame:
                where[sect], by[sect] = frame, caller
    out: list[tuple[str, str, str]] = []
    for k, table in ledger.items():
        f = where.get(k, "")
        if f and is_test(f):
            out.append(("TEST", k, f"{table} (from {f})"))
        else:
            via = f or "no apps/ frame in its traceback"
            tail = f" (called from {by[k]})" if by.get(k) else ""
            out.append(("PROD", k, f"{table} via {via}{tail}"))
    return sorted(out, key=lambda row: "\t".join(row).encode())


def grants_db(ctx: Ctx, action: str, template: str = "") -> tuple[int, str]:
    """Prepare the least-privilege role and its template, or tear the template down."""
    source = ""
    if action == "prepare":
        rc, out = _bash(
            ctx,
            "command -v db_template_name >/dev/null 2>&1 || exit 0\n"
            "s=$(db_template_name 2>/dev/null) || exit 0\n"
            '[ -n "$s" ] && db_exists "$s" >/dev/null 2>&1 && printf %s "$s"\nexit 0',
        )
        source = out.strip() if rc == 0 else ""
    env = {
        "DJB_GRANTS_ACTION": action,
        "DJB_GRANTS_TEMPLATE": template,
        "DJB_GRANTS_SOURCE": source,
        "DJB_GRANTS_ROLE": ctx.env.get("DJB_GATE_GRANTS_ROLE") or GRANTS_ROLE,
        "DJB_GRANTS_SECRET": GRANTS_SECRET,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    _flush()
    try:
        done = subprocess.run(
            ["uv", "run", "python", "-"],
            cwd=ctx.root,
            env=_env(ctx, env),
            input=GRANTS_DB.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        return 2, f"uv could not be started: {exc}"
    return done.returncode, done.stdout.decode(errors="replace")


def grants_pass(ctx: Ctx, run: Run, workers: int, seed_: int, args: Sequence[str]) -> int:
    """One pass as the least-privilege role: a product write to a ledger is red; 0/1/2."""
    if run.product:
        print("  grants pass: the product's own targets", flush=True)
    typed = ctx.env.get("DJB_GATE_GRANTS_PASS")
    if typed in ("0", "off", "no"):
        print(f"  grants pass: NOT run — DJB_GATE_GRANTS_PASS={typed} was typed", flush=True)
        return 0
    if run.store or (run.pr and not run.product):
        why = "--store-durations is a measurement" if run.store else ""
        why += "--pr is a narrowed run" if run.pr and not run.product else ""
        print(f"  grants pass: NOT run — {why}", flush=True)
        return 0
    if ctx.env.get("CI") and not typed:
        print(
            "  grants pass: NOT run on CI — it is the bank's (DJB_GATE_GRANTS_PASS=1 runs it here)",
            flush=True,
        )
        return 0
    kept = [a for a in args if not a.startswith("--djb-scope-counts=")]
    rc, prep = grants_db(ctx, "prepare")
    if rc != 0:
        last = prep.rstrip("\n").splitlines()[-1:] or [""]
        say(
            "!! the grants pass COULD NOT LOOK — the least-privilege role or its template",
            f"   could not be made: {last[0]}",
        )
        return 2
    line = next((x for x in prep.splitlines() if x.startswith("template=")), "")
    words = line.split()
    template = words[0][len("template=") :] if words else ""
    ledgers = next(
        (re.sub(r"^ledgers=[0-9]+:", "", w) for w in words if w.startswith("ledgers=")), ""
    )
    if not template or not ledgers:
        say("!! the grants pass COULD NOT LOOK — the template step printed no template")
        return 2
    role = ctx.env.get("DJB_GATE_GRANTS_ROLE") or GRANTS_ROLE
    print(f"  grants pass: one pytest pass connected as {role} — deploy/grants.sql.py's grants,")
    print(f"               UPDATE and DELETE revoked on: {ledgers.replace(',', ', ')}")
    print(f"               ({line.split(' ', 1)[1] if ' ' in line else ''})", flush=True)
    env = {
        "DATABASE_USER": role,
        "DATABASE_PASSWORD": GRANTS_SECRET,
        "DJB_TEST_DB_TEMPLATE": template,
    }
    argv = [TEST_SH, "-n", str(workers), f"--randomly-seed={seed_}", *kept]
    rc, text = _captured(ctx, argv, env)
    grants_db(ctx, "teardown", template)
    judged_run = rc not in (0, 3, 4, 5)
    judged = grants_judge(text, ledgers.split(",")) if judged_run else []
    denied = [f"     {k} — {d}" for kind, k, d in judged if kind == "PROD"]
    tests = failed_in_summary(text) if judged_run and not denied else []
    if judged_run and not denied:
        # Invariant: the verdict precedes the transcript it qualifies; pytest's count is not it.
        print(
            f"  grants pass: no product path wrote to a ledger. {len(tests)} test(s) failed on a "
            "privilege"
        )
        print(
            "               the suite itself needs (a test's own ledger write, a flush after one) —"
        )
        print("               NOT a verdict about the tree: pass 1 ran them green as the owner.")
        print(
            "               pytest's transcript of the pass follows; the list after it is the same."
        )
    sys.stdout.write(text)
    sys.stdout.flush()
    if rc == 0:
        print(
            "  grants pass: green — no path the suite drives updated or deleted a row of "
            f"{ledgers.replace(',', ', ')}",
            flush=True,
        )
        return 0
    if run.product and rc == 5:
        print(f"  grants pass: {' '.join(_targets(args))} has no tests yet — nothing to run")
        return 0
    if rc in (3, 4, 5):
        say(f"!! the grants pass DID NOT RUN THE SUITE (pytest exit {rc}) — could not look.")
        return 2
    if denied:
        say(
            "",
            "!! THE GRANTS PASS IS RED: the least-privilege role was REFUSED an UPDATE or",
            "   DELETE on an append-only table, from product code the suite drives (house",
            "   rule 20's third belt). Pass 1 ran the same tests as the owner and they",
            "   passed. Each test, the ledger, the innermost apps/ frame, and the product",
            "   frame in another app that called into it when there is one:",
            *denied,
        )
        return 1
    print(f"  grants pass: {len(tests)} test(s) failed on a privilege the suite itself needs:")
    for kind, k, d in judged:
        if kind == "TEST":
            print(f"               test-owned ledger write: {k} — {d}")
    for t in tests:
        print(t)
    sys.stdout.flush()
    return 0


def bank_partition(ctx: Ctx, run: Run, decision: Decision) -> int:
    """Bank the partition's verdict only for a whole, measured, unbent run; 0 or 2."""
    if decision.mode == "product":
        print("  partition verdict NOT banked: a product tree decided no platform partition.")
    elif run.pr:
        print("  partition verdict NOT banked: --pr is a narrowed run and the platform")
        print("  portion was deselected, so this run has nothing to say about it.", flush=True)
    elif run.shard is not None:
        print(
            f"  shard {run.shard[0]}/{run.shard[1]} banks nothing: a part of the collection has "
            "nothing to say"
        )
        print("  about the whole — not here, and not in the verdict ledger at the end.")
    elif run.store:
        print("  --store-durations banks nothing: one pass ran, and it ran to be timed.")
    elif decision.mode != "skip":
        if not decision.bankable:
            print("  partition verdict NOT banked: the environment is bent (reason above).")
        elif _streamed(ctx, [*BANK, "--key", decision.key]) != 0:
            say("!! the partition verdict could not be banked (exit 2).")
            return 2
    sys.stdout.flush()
    return 0


def database_name(ctx: Ctx) -> str:
    """This checkout's database: the environment's, else `db.sh`'s derivation."""
    if ctx.env.get("DATABASE_NAME"):
        return ctx.env["DATABASE_NAME"]
    rc, out = _bash(ctx, 'printf %s "${DATABASE_NAME:-}"')
    return out.strip() if rc == 0 else ""


def own_tree_census(ctx: Ctx) -> int:
    """Every instance this checkout made is declared; in process lifetime no schedule leaks."""
    name = database_name(ctx)
    if not name:
        say("!! THE OWN-TREE MACHINERY CENSUS COULD NOT BE TAKEN — no DATABASE_NAME derived.")
        return 2
    rc, text = _captured(ctx, [SWEEP, "--only", name])
    sys.stdout.write(text)
    if rc != 0:
        if "UNRECOGNIZED" in text:
            say(
                "!! THIS CHECKOUT MADE SOMETHING NO DECLARED CLASS CLAIMS (exit 2).",
                "   The shape is named above. It carries a checkout-derived identity, so this",
                "   repository built it, and scripts/lifecycle.sh does not know what it is —",
                "   which means this census cannot say what it just looked at, and a broom",
                "   pointed at this machine would not know whether to touch it.",
                "   Declare the class in scripts/lifecycle.sh (name, identity, enumerate,",
                "   liveness, destroy, warm). Do NOT widen an existing pattern to swallow it.",
            )
        else:
            say(
                f"!! THE OWN-TREE MACHINERY CENSUS COULD NOT BE TAKEN (exit {rc}).",
                "   No docker, no Postgres, no Temporal, or no checkout to derive liveness",
                "   from. A census that could not look has not cleared anything, and an",
                "   instrument reporting a clean floor it never read is the class this leg",
                "   exists to refuse.",
            )
        return 2
    print(f"  every instance {name} owns belongs to a declared class", flush=True)
    rc, answered = _captured(
        ctx,
        [
            "uv",
            "run",
            "python",
            "-c",
            "import config.settings.local as s; print(s.TEMPORAL_MACHINERY_LIFETIME)",
        ],
    )
    lifetime = answered.strip().splitlines()[-1] if rc == 0 and answered.strip() else ""
    if not lifetime:
        say(
            "!! COULD NOT READ TEMPORAL_MACHINERY_LIFETIME from config/settings/local.py.",
            "   Without it this leg cannot tell a leaked schedule from a legitimate one,",
            f"   and guessing either way is worse than saying so (exit 2).{tool_said(answered)}",
        )
        return 2
    if lifetime != "process":
        print(f"  lifetime class is '{lifetime}': durable Schedules for this queue are")
        print("  CORRECT here, so the zero-schedules property does not apply (ADR")
        print("  platform-lifecycle-1). Nothing was asserted about them.")
        print("  Nor does the open-execution property: in deployment lifetime a running")
        print("  execution on this queue is the product working. Nothing was asserted")
        print("  about those either.", flush=True)
        return 0
    return process_lifetime(ctx, name)


def _swept(ctx: Ctx, argv: Sequence[str]) -> tuple[int, str]:
    """`sweep.sh` with its text printed after it ran; its exit and its LAST `!!` line, unled."""
    rc, text = _captured(ctx, argv)
    sys.stdout.write(text)
    sys.stdout.flush()
    said = [ln.lstrip()[2:].strip() for ln in text.splitlines() if ln.lstrip().startswith("!!")]
    return rc, said[-1] if said else ""


def process_lifetime(ctx: Ctx, name: str) -> int:
    """No durable Schedule on this queue, and no stranded open execution when nothing polls."""
    rc, cause = _swept(ctx, [SWEEP, "--class", "schedule", "--only", name, "--assert-none"])
    if rc == 2:
        return could_not_look(
            ctx,
            cause,
            "!! THE SCHEDULE CENSUS COULD NOT BE TAKEN — see above. Nothing was asserted.",
            CAUSE,
        )
    if rc != 0:
        return finding(
            "THIS TREE LEAKED A DURABLE TEMPORAL SCHEDULE.",
            "Lifetime class is 'process' (ADR platform-lifecycle-1), which creates no",
            "Schedule object ever — and the server holds one for this checkout's queue.",
            "A Schedule is infinitely durable and this checkout's identity is not: when",
            "the checkout goes, the schedule goes on starting workflows nothing will",
            "ever poll, forever. That is the leak this leg exists to close.",
            "Either is a fix: start the worker once (./scripts/worker.sh), whose startup",
            "deletes this checkout's own legacy schedules; or sweep it directly with",
            f"  ./scripts/sweep.sh --sweep --class schedule --only {name}",
        )
    print("  process lifetime: this queue owns no durable Schedule", flush=True)
    queue = f"djb-{name.removeprefix('djb_')}"
    rc, out = _bash(
        ctx, f'. scripts/lifecycle.sh >/dev/null 2>&1 || exit 1\nlc_queue_pollers "{queue}"'
    )
    pollers = out.strip()
    pollers = pollers if pollers.isdigit() else "0"
    if rc == 0 and pollers != "0":
        print(f"  {pollers} poller(s) on {queue} right now: open executions here are")
        print("  WORK, not strands (scripts/lifecycle.sh declares this class's liveness as")
        print("  pollers on its queue, positive evidence only). Nothing was asserted about")
        print("  them.", flush=True)
        return 0
    rc, cause = _swept(ctx, [SWEEP, "--class", "open-execution", "--only", name, "--assert-none"])
    if rc == 2:
        return could_not_look(
            ctx,
            cause,
            "!! THE OPEN-EXECUTION CENSUS COULD NOT BE TAKEN — see above. Nothing was asserted.",
            CAUSE,
        )
    if rc != 0:
        return finding(
            "THIS TREE STRANDED A RUNNING TEMPORAL EXECUTION.",
            f"Nothing is polling {queue}, and the server is holding open run(s)",
            "on it — named above with how long each has been running. An execution",
            "on a queue with no poller never advances and never ends: it sits in the",
            "namespace forever, and this checkout's identity does not. That is how",
            "1,061 of them accumulated under a green census.",
            "Either is a fix: start the worker (./scripts/worker.sh) if that work is",
            "real and should finish; or END EACH RUN NAMED ABOVE BY HAND, with the",
            "destroy verb its own class declares (scripts/lifecycle.sh, open-execution):",
            "  bash -c '. scripts/lifecycle.sh && lc_temporal workflow terminate "
            "--workflow-id <an id above>'",
            "AND NOT THE BROOM, which is the line that used to be printed here and",
            "which does nothing at all in this exact situation: this checkout's OWN",
            "open executions are declared NOT disposable, so no sweep of any kind",
            "touches one — owning a thing is not a licence to destroy it. That stance",
            "is right and stays: a poller count is a racy thing to kill on (a worker",
            "restarting reads as zero), so nothing gets a flag meaning 'destroy my own",
            "running work'. You name the run instead, one at a time, on purpose.",
            "Whatever started them and walked away is the defect; this is the belt.",
        )
    print("  process lifetime: this queue strands no open execution", flush=True)
    return 0


def slot(ctx: Ctx, run: Run) -> hold.Hold | None:
    """One pytest slot (`bank`: every slot), the lease first when the mode demands it."""
    lease_first = bool(ctx.env.get("GATE_SLOT_LEASE_FIRST"))
    held = ctx.env.get("GATE_LEASE", "")
    lease = hold.Hold("lease", paths=[Path(held)]) if held else hold.Hold("lease")
    try:
        return hold.acquire_slot(
            "bank" if run.bank else "full", lease_first=lease_first, lease=lease
        )
    except hold.Refused as exc:
        say(
            "!! no pytest slot — see above. Nothing was judged about this tree.",
            f"   cause: {exc.cause}",
        )
        return None


def suite(ctx: Ctx, run: Run, decision: Decision) -> int:
    """The two passes and the grants pass inside one slot, then the partition's bank; 0/1/2."""
    if decision.mode == "product":
        if not decision.targets:
            print(
                "  PRODUCT PASS — no product app yet: nothing to run, and no grants pass",
                flush=True,
            )
            return bank_partition(ctx, run, decision)
        run = replace(run, product=True)
    taken = slot(ctx, run)
    if taken is None:
        return 2
    try:
        workers = taken.workers or hold.slot_workers(taken.total or 1)
        ctx = Ctx(ctx.root, ctx.mode, {**ctx.env, "DJB_GATE_SLOT_WORKERS": str(workers)})
        scope = " ".join(decision.targets)
        if decision.mode == "product":
            print(f"  PRODUCT PASS — {run.run_word}: {scope}")
        elif decision.mode == "skip":
            print(f"  PLATFORM PARTITION SKIPPED — banked under {decision.key}")
            print(f"  {run.run_word} ONLY: {scope or '<nothing outside the partition>'}")
        else:
            print(f"  PLATFORM PARTITION RUNNING — no banked verdict for {decision.key}")
            print(f"  {run.run_word} the WHOLE suite")
        seed_ = seed(ctx.env)
        if seed_ is None:
            return 2
        print(f"  {run.run_word} --randomly-seed={seed_} (replay a red order with it)")
        print(f"  workers:    -n {workers} ({taken.phrase or 'this slot’s share'})")
        print("              NOT -n auto, and the same number on BOTH passes, which is what pins")
        print("              the worker assignment and keeps this leg's meaning narrow.")
        hold.nominal(hold.NOMINAL_FULL, "NOMINAL_FULL", ())
        counts_dir = ctx.env.get("GATE_PR_COUNTS_DIR", "")
        made = ""
        if not counts_dir:
            made = counts_dir = tempfile.mkdtemp(prefix="djb-full-counts.")
        splits = split_args(ctx, run)
        if splits is None:
            return 2
        args = [*decision.targets, *splits]
        if made:
            args.append(f"--djb-scope-counts={made}")
        rc = passes(ctx, run, workers, seed_, args, counts_dir)
        if rc:
            return rc
        rc = grants_pass(ctx, run, workers, seed_, args)
        if rc:
            return rc
    finally:
        taken.release()
        if made:
            shutil.rmtree(made, ignore_errors=True)
    return bank_partition(ctx, run, decision)


def run(ctx: Ctx) -> int:
    """Census before, partition, the passes, census after, the own-tree census; first non-0."""
    plan = Run.of(ctx.env)
    rc, before, _ = temporal_census(ctx, "pre-suite")
    if rc:
        return rc
    rc, decision = partition(ctx, plan)
    if rc or decision is None:
        return rc or 2
    rc = suite(ctx, plan, decision)
    if rc:
        return rc
    rc, _, orphans = temporal_census(ctx, "post-suite")
    if rc:
        return rc
    rc = new_orphans(before, orphans)
    if rc:
        return rc
    return own_tree_census(ctx)


#: The leg's banner under `--passes 1`.
BANNER_ONE_PASS = (
    "pytest (ONCE — --passes 1, under ONE seed and ONE OF THIS MACHINE'S PYTEST SLOTS; the second "  # noqa: S105 — a banner sentence that mentions passes, not a credential
    "run that would prove this one left nothing behind is the acceptance box's)"
)

LEG = Leg(
    "pytest-x2",
    "pytest-x2",
    "pytest (twice, both passes under ONE seed and ONE OF THIS MACHINE'S PYTEST SLOTS, nothing in "
    "between — the second run proves the first left nothing behind)",
    run,
    None,
    frozenset({"full"}),
    ARGV,
    ("temporal-census", "partition", "own-tree-census"),
)
