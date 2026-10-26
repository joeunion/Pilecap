"""`pm_push --bank --on-boxes N`: one unit of the gate per verifier box, one composed row."""

# does-not-cover: the real wrapper — every box call is `scripts/verifier_box.sh` through `box.bank`.
# does-not-cover: a SIGKILL — the boxes' own lifetime and idle reaper are the only teardown then.
# does-not-cover: a machine with no pgrep — no children are killed; it says so, and still downs.

from __future__ import annotations

import contextlib
import functools
import io
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from quality.djb import ledger
from quality.djb.box import bank as boxes
from quality.djb.box.census import tab_fields
from quality.djb.rituals.verify_start import Died, err, out

NOTHING_PUSHED = "Nothing was pinned and nothing was pushed."
#: The suite leg a one-pass plan rewrites as `<leg>/1`; the seam grammar's one member.
SUITE_LEG = "pytest-x2"


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _said(body: Callable[..., int], *args: object, **kw: object) -> tuple[int, str]:
    """A `box.bank` body's status and what it printed, as the shell's `$(…)` read it."""
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        rc = body(*args, **kw)
    return rc, sink.getvalue().rstrip("\n")


def _read(path: Path, default: str = "") -> str:
    return boxes.read_or(path, default).strip(" \r\n")


def _plan_rows(plan: Path) -> Iterator[tuple[str, str, str, str, str]]:
    for line in boxes.read_lines(plan):
        label, unit, az, shard, passes = tab_fields(line, 5)
        if label:
            yield label, unit, az, shard, passes


def _together(jobs: list[Callable[[], object]]) -> None:
    """The shell's `( … ) &` per job then a bare `wait`: every job run, every one joined."""
    workers = [threading.Thread(target=job, daemon=True) for job in jobs]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()


def _children() -> list[str]:
    """This process's live children by pid: every `spawn` the arm's threads still wait on."""
    try:
        done = subprocess.run(
            ["pgrep", "-P", str(os.getpid())], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return []
    return done.stdout.split()


def _log_tree(log: Path) -> str:
    for record in boxes.awk_records(log):
        if "The tree it ran on was" in record:
            return boxes.awk_fields(record)[-1].removesuffix(".")
    return ""


def _log_composed(log: Path) -> str:
    for record in boxes.awk_records(log):
        if record.startswith("  composed-of: "):
            return record.removeprefix("  composed-of: ")
    return ""


def _log_wall(log: Path) -> str:
    for record in boxes.awk_records(log):
        if record.startswith("ok: all checks passed ("):
            return boxes.awk_fields(record)[-1].removeprefix("(").removesuffix("s)")
    return ""


class Arm:
    """One `--on-boxes` bank: the plan, the boxes, the composition, the row, the teardown."""

    def __init__(self, root: Path, gate: Path, n: int, leak_proof: str) -> None:
        self.root, self.gate, self.n, self.leak_proof = root, gate, n, leak_proof
        vb = root / "scripts" / "verifier_box.sh"
        if not (vb.is_file() and os.access(vb, os.X_OK)):
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: no executable verifier wrapper at {vb} — there is nothing to bank on",
            )
        self.bank = boxes.Bank(
            vb=str(vb),
            ttl_hours=_env("DJB_BANK_BOX_TTL_HOURS", "1"),
            idle_minutes=_env("DJB_BANK_BOX_IDLE_MINUTES", "30"),
            retry_seconds=_env("DJB_BANK_DETACH_RETRY_SECONDS", "15"),
            proof_workers=_env("DJB_BANK_PROOF_WORKERS", "16"),
            suite_leg=SUITE_LEG,
            root=str(root),
            env=dict(os.environ),
        )

    # --- the whole of it --------------------------------------------------------------

    def run(self) -> int:
        """0 with ONE row banked · 1 a red shard named, no row · 2 the reason named, no row."""
        previous = {
            sig: signal.signal(sig, self._interrupted) for sig in (signal.SIGINT, signal.SIGTERM)
        }
        armed = False
        rc = 2
        try:
            self.prepare()
            armed = True
            rc = self.measure()
            return rc
        except SystemExit as stop:
            rc = stop.code if isinstance(stop.code, int) else 2
            raise
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if armed:
                sys.stdout.flush()
                if shutil.which("pgrep") is None:
                    out("teardown: children not read — no pgrep")
                self.bank.workers = " ".join([*self.bank.workers.split(), *_children()])
                boxes.bank_boxes_teardown(self.bank, str(rc))

    @staticmethod
    def _interrupted(signum: int, _frame: object) -> None:
        raise SystemExit(130 if signum == signal.SIGINT else 143)

    # --- before any box -----------------------------------------------------------------

    def prepare(self) -> None:
        root, bank, n = self.root, self.bank, self.n
        try:
            sink = Path(tempfile.mkdtemp(prefix="djb-bank-boxes."))
        except OSError:
            raise Died(
                NOTHING_PUSHED, "pm_push: could not make an exit sink for the bank"
            ) from None
        if f"{sink}/".startswith(f"{root.resolve()}/") or f"{sink}/".startswith(f"{root}/"):
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: the exit sink ({sink}) landed inside {root}. Every byte in the\n"
                "   checkout is part of the tree this bank keys a verdict on; point TMPDIR\n"
                "   somewhere outside it.",
            )
        bank.sink = str(sink)
        bank.tsv = str(sink / "boxes.tsv")
        Path(bank.tsv).write_text("")
        try:
            self.tree = ledger.measured_tree(root)
        except (ledger.Mismatch, OSError):
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: could not read the measured tree of {root} — there is nothing to key a"
                " verdict on",
            ) from None
        self.declared = ",".join(ledger.full_legs(root))
        if not self.declared:
            raise Died(
                NOTHING_PUSHED,
                "pm_push: scripts/check.sh declares no FULL_LEGS — a composed row could name no"
                " leg set",
            )
        bank.tree8 = self.tree[:8]
        bank.arung = f"bank-{bank.tree8}-acceptance"
        _, self.acheckout = _said(boxes.bank_boxes_box_checkout, str(root))
        self.planpasses = "1" if self.acheckout else "2"
        self.nform = nline = ""
        if self.leak_proof == "nightly":
            self.acheckout, self.planpasses = "", "1"
            self.nform, nline = ledger.nightly_source(sink / "nightly", self.tree)
        out(f"pm_push --bank --on-boxes {n}: the full gate, one unit per verifier box.")
        out(f"  tree          {self.tree}")
        out(f"  sink          {sink}")
        out(f"  wrapper       {bank.vb}")
        out(
            f"  box lifetime: {bank.ttl_hours}h hard, {bank.idle_minutes}m idle - the box reaps"
            " itself if the Mac dies"
        )
        out("  This Mac MEASURES NOTHING: it takes no machine lease and no pytest slot,")
        out("  so every builder's --loop on this box keeps its own slot throughout.")
        if nline:
            out(nline)
        out("")
        self.listing = sink / "list-legs.tsv"
        out(f"pm_push --bank --on-boxes: reading the units — {self.gate} --list-legs")
        sys.stdout.flush()
        with self.listing.open("w") as listed, (sink / "list-legs.err").open("w") as errs:
            lrc = subprocess.run(
                [str(self.gate), "--list-legs"],
                cwd=root,
                stdout=listed,
                stderr=errs,
                stdin=subprocess.DEVNULL,
                check=False,
            ).returncode
        if lrc != 0:
            err((sink / "list-legs.err").read_text(errors="replace").rstrip("\n"))
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: ./scripts/check.sh --list-legs exited {lrc}. A gate that cannot say"
                " what its\n   units are cannot be split across boxes, and a plan guessed from"
                " anything else\n   is the hand list this repository refuses everywhere.\n"
                "   Nothing was launched, nothing was banked and nothing was pushed.",
            )
        zones = sink / "zones.txt"
        if boxes.bank_boxes_zones_read(bank, bank.vb, str(zones)) != 0:
            with contextlib.suppress(OSError):
                err(Path(f"{zones}.err").read_text(errors="replace").rstrip("\n"))
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: could not read the zones — {bank.vb} zones answered nothing this bank"
                " can spread\n   over. Spot capacity is a per-availability-zone fact and a bank"
                " in one zone is a\n   bank that loses every box to one capacity event; rather"
                " than launch blind, this\n   one refuses. Nothing was launched, nothing was"
                " banked and nothing was pushed.",
            )
        bank.zones = " ".join(zones.read_text(errors="replace").split("\n")).rstrip(" ")
        out(f"pm_push --bank --on-boxes: zones {bank.zones}")
        out("    read from the wrapper, never typed here: one box per zone in turn, so a")
        out("    capacity event in one zone costs a shard and not a wave.")
        out("")
        self.plan = sink / "plan.tsv"
        bank.plan = str(self.plan)
        prc, drawn = _said(
            boxes.bank_boxes_plan,
            str(self.listing),
            n,
            self.planpasses,
            bank.zones,
            suite_leg=SUITE_LEG,
        )
        if prc != 0:
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: the bank could not draw a plan for {n} boxes. Nothing was launched.",
            )
        self.plan.write_text(f"{drawn}\n" if drawn else "")
        planned = sum(1 for line in drawn.split("\n") if line)
        if planned != n:
            raise Died(
                NOTHING_PUSHED,
                f"pm_push: the plan came to {planned} shards for {n} boxes. One shard is one box"
                " and\n   one box is one shard; a plan that does not add up is never a smaller"
                " bank.",
            )
        self._say_plan()

    def _say_plan(self) -> None:
        bank, root = self.bank, self.root
        out("pm_push --bank --on-boxes: the plan, derived from that listing —")
        for label, unit, _az, shard, passes in _plan_rows(self.plan):
            sharded = f" --shard {shard}" if shard else ""
            once = " --passes 1" if passes == "1" else ""
            out(f"    {label}\t--leg {unit}{sharded}{once}")
        if self.planpasses == "1" and self.leak_proof != "nightly":
            out("    ONE pass per suite shard (ADR gate-1's amendment): the whole-suite")
            out("    two-pass leak proof runs on the acceptance box below, and the row is")
            out("    not written until it comes home green.")
        fe_dir = os.environ.get("FE_FRONTEND_DIR") or "frontend"
        bank.fe_cmd = ""
        if (root / fe_dir).is_dir():
            _, fecheckout = _said(boxes.bank_boxes_box_checkout, str(root))
            if fecheckout:
                bank.fe_cmd = boxes.frontend_remote_line(fecheckout, fe_dir)
                out(f"    every shard, before its unit: {fe_dir}/ installed on its box —")
                out("    fe_leg_frozen_lockfile (scripts/fe_gate.sh), CI's every-row step; the")
                out("    listing's needs name no frontend toolchain, so no shard is left out.")
            else:
                out(f"    WARNING: {fe_dir}/ is on this tree and no shard installs it —")
                out("    deploy/verifier/bake.sh does not say where a box's checkout lives. A")
                out("    drive that needs the toolchain will say it could not look.")
        else:
            out(f"    no {fe_dir}/ on this tree — no shard installs a frontend toolchain.")
        out("")
        if self.leak_proof == "nightly":
            bank.accept_note = (
                "acceptance: no box — --leak-proof nightly: the second whole pass is the\n"
                f"   nightly's ({self.nform}), and so is the map: the fold harvests the latest"
                " green\n   nightly's scripts/test_impact.json. This bank writes neither."
            )
            out("pm_push --bank --on-boxes: NO acceptance box — --leak-proof nightly.")
            out("    ONE pass per suite shard; the row names the nightly as its leak proof.")
        elif not self.acheckout:
            bank.accept_note = (
                "acceptance: no box — deploy/verifier/bake.sh could not be read, so\n"
                "   the box's checkout path is unknown. The map is NOT written and the loop"
                " keeps\n   the closure scope; the bank is unaffected."
            )
            out(f"pm_push --bank --on-boxes: NO acceptance box — {root}/deploy/verifier/bake.sh")
            out("    could not be read for the box's checkout path. The test-impact map will")
            out("    not be rewritten by this bank; nothing else changes.")
        else:
            _, bank.accept_az = _said(boxes.bank_boxes_zone_at, bank.zones, self.n)
            out("pm_push --bank --on-boxes: and ONE more box, outside the verdict —")
            out(
                f"    {bank.arung}\tthe whole suite twice (contexts, then plain) ->"
                " scripts/test_impact.json"
            )
            out(f"    in {bank.accept_az}")
            out("    Its status is PRINTED and composed nowhere: a measurement may not refuse")
            out("    a claim every shard passed.")
        out("")

    # --- the boxes ------------------------------------------------------------------------

    def measure(self) -> int:
        bank, sink = self.bank, Path(self.bank.sink)
        rows = list(_plan_rows(self.plan))
        out(f"pm_push --bank --on-boxes: bringing {self.n} boxes up, concurrently.")
        jobs: list[Callable[[], object]] = [
            functools.partial(
                boxes.bank_boxes_up_one,
                bank,
                label,
                f"bank-{bank.tree8}-{label}",
                az,
                f"{sink}/up-{label}.log",
                "1",
            )
            for label, _u, az, _s, _p in rows
        ]
        if self.acheckout:
            jobs.append(
                lambda: boxes.bank_boxes_up_one(
                    bank, "acceptance", bank.arung, bank.accept_az, f"{sink}/up-acceptance.log", "0"
                )
            )
        _together(jobs)
        if self.acheckout:
            bank.accept_id = _read(sink / "acceptance.id")
            if not bank.accept_id:
                if self.planpasses == "1":
                    tail = (
                        ", and this bank will be\n   REFUSED — one pass was measured and nothing"
                        " can prove it left nothing behind."
                    )
                else:
                    tail = " and the loop keeps\n   the closure scope; every shard is unaffected."
                bank.accept_note = (
                    f"acceptance: no box — it did not come up (see\n   {sink}/up-acceptance.log)."
                    f" The map is NOT written{tail}"
                )
        failed = [r[0] for r in rows if _read(sink / f"{r[0]}.up.rc", "2") != "0"]
        if failed:
            boxes.bank_boxes_table(bank)
            err(f"!! pm_push --bank --on-boxes: a box did not come up: {' '.join(failed)}")
            err(f"   Their up logs are under {sink}. Nothing was measured and no")
            err("   verdict was composed; every box that DID come up is being taken down.")
            if not os.environ.get("DJB_VERIFIER_ON_DEMAND_OK"):
                err(
                    "   If a log above says Spot was refused: a shard NEVER falls back to on-demand"
                )
                err("   on its own — N shards doing that is N on-demand boxes nobody asked for. To")
                err("   buy them deliberately, type the reason and run the bank again:")
                err('     DJB_VERIFIER_ON_DEMAND_OK="<why this wave is worth on-demand money>" \\')
                err("       ./scripts/pm_push.sh --bank --on-boxes <N>")
            return 2
        out("pm_push --bank --on-boxes: detaching one unit of the gate on each box.")

        def detach(label: str, unit: str, shard: str, passes: str) -> None:
            lid = _read(sink / f"{label}.id")
            boxes.bank_boxes_frontend_install(bank, label, lid)
            boxes.write_line(sink / f"{label}.began", int(time.time()))
            boxes.bank_boxes_detach(
                bank, label, lid, unit, shard, passes, f"{sink}/leg-{label}.log"
            )

        _together([functools.partial(detach, r[0], r[1], r[3], r[4]) for r in rows])
        failed = [r[0] for r in rows if _read(sink / f"{r[0]}.leg.rc", "2") != "0"]
        if failed:
            boxes.bank_boxes_table(bank)
            err(f"!! pm_push --bank --on-boxes: a unit could not be detached: {' '.join(failed)}")
            err("   That is the transport or the wrapper, never a red tree: nothing was")
            err("   measured and no verdict was composed.")
            return 2
        out("pm_push --bank --on-boxes: waiting on every shard (the wall is the slowest one).")
        sys.stdout.flush()
        waits: list[Callable[[], object]] = []
        if bank.accept_id:
            bank.acmd = boxes.acceptance_remote_line(self.acheckout, bank.arung, bank.proof_workers)
            waits.append(self._acceptance)
        waits += [functools.partial(self._wait, r[0]) for r in rows]
        _together(waits)
        boxes.bank_boxes_retry_reclaimed(bank)
        arc = _read(sink / "acceptance.rc").replace(" ", "")
        boxes.bank_boxes_acceptance_report(bank, arc)
        return self.compose(rows)

    def _acceptance(self) -> None:
        bank, sink = self.bank, Path(self.bank.sink)
        began = int(time.time())
        rc = boxes.vb_call(bank, ["run", bank.accept_id, "--", bank.acmd], sink / "acceptance.log")
        boxes.write_line(sink / "acceptance.rc", rc)
        boxes.write_line(sink / "acceptance.wall", int(time.time()) - began)
        boxes.bank_boxes_fetch_acceptance_files(bank, str(rc))

    def _wait(self, label: str) -> None:
        bank, sink = self.bank, Path(self.bank.sink)
        wid = _read(sink / f"{label}.id")
        rc = boxes.vb_call(bank, ["wait", wid, "leg"], sink / f"wait-{label}.log")
        boxes.write_line(sink / f"{label}.wait.rc", rc)
        began = int(_read(sink / f"{label}.began", "0") or 0)
        boxes.write_line(sink / f"{label}.wall", int(time.time()) - began)
        boxes.bank_boxes_fetch_shard(bank, label, wid)

    # --- the composition ------------------------------------------------------------------

    def compose(self, rows: list[tuple[str, str, str, str, str]]) -> int:
        bank, sink, tree = self.bank, Path(self.bank.sink), self.tree
        lost: list[str] = []
        red: list[str] = []
        foreign: list[str] = []
        kbad: list[str] = []
        union: list[str] = []
        pytest_wall = 0
        onepass = any(r[4] == "1" for r in rows)
        for label, unit, _az, shard, passes in rows:
            log = sink / f"{label}.log"
            if not (log.is_file() and log.stat().st_size):
                lost.append(
                    f"{label}: no log came back from the box (fetch log: {sink}/fetch-{label}.log)"
                )
                continue
            rc = _read(sink / f"{label}.rc").replace(" ", "")
            treev, composed, legwall = _log_tree(log), _log_composed(log), _log_wall(log)
            if not legwall.isdigit():
                legwall = _read(sink / f"{label}.wall", "0")
            if not legwall.isdigit():
                legwall = "0"
            boxes.write_line(sink / f"{label}.legwall", legwall)
            boxes.write_line(sink / f"{label}.tree", treev)
            if boxes.saw_reclaim(f"{sink}/wait-{label}.log"):
                lost.append(
                    f"{label}: the box was RECLAIMED mid-flight — the verdict is LOST, never red"
                )
                continue
            if rc == "2":
                lost.append(
                    f"{label}: the shard exited 2 — enforcement broken on that box, which outranks"
                    " a pass"
                )
                continue
            if rc not in ("0", "1"):
                lost.append(
                    f"{label}: no exit status came back from the box (read '{rc or '<empty>'}')"
                )
                continue
            if not treev:
                lost.append(
                    f"{label}: the log names no tree — nothing says WHICH bytes that shard measured"
                )
                continue
            if treev != tree:
                foreign.append(
                    f"{label}: the box ran {treev}\n              this bank keys on {tree}"
                )
                continue
            if not composed:
                lost.append(
                    f"{label}: the log carries no composed-of: line — nothing says WHICH legs that"
                    " shard ran"
                )
                continue
            union.append(composed)
            if passes:
                self._passes_agree(kbad, label, unit, passes, composed)
            if rc == "1":
                sharded = f" --shard {shard}" if shard else ""
                red.append(
                    f"{label}: --leg {unit}{sharded} on {_read(sink / f'{label}.id')} exited 1"
                )
                if any(r.startswith("FAILED ") for r in boxes.awk_records(log)):
                    _, line = _said(
                        boxes.bank_boxes_first_failing,
                        str(log),
                        label,
                        boxes.log_seed_of(str(log)),
                        workers=bank.proof_workers,
                    )
                    red.append(f"         {line}")
            if f",{unit}," in ",pytest-x2,":
                pytest_wall = max(pytest_wall, int(legwall))
        self._k_agree(kbad, rows)
        shard_legs = {
            m.split("/")[0] if m.rsplit("/", 1)[-1].isdigit() else m
            for m in ",".join(union).split(",")
            if m
        }
        listing_legs = {
            m
            for line in boxes.read_lines(self.listing)
            for m in tab_fields(line, 4)[3].split(",")
            if m
        }
        declared_legs = {m for m in self.declared.split(",") if m}
        missing = sorted(listing_legs - shard_legs)
        extra = sorted(shard_legs - listing_legs)
        uncovered = sorted(declared_legs - shard_legs)
        if onepass and self.leak_proof != "nightly":
            self._proof(lost, red)
        boxes.bank_boxes_table(bank)
        if lost:
            err("!! pm_push --bank --on-boxes: a shard's verdict could not be read. NO ROW WAS")
            err("   WRITTEN and nothing was pushed — a bank is a claim about every unit, and 2")
            err("   (could not look) outranks any pass:" + "".join(f"\n     {x}" for x in lost))
            return 2
        if foreign:
            err("!! pm_push --bank --on-boxes: a box measured a DIFFERENT tree. NO ROW WAS")
            err("   WRITTEN and nothing was pushed:" + "".join(f"\n     {x}" for x in foreign))
            err("   A verdict composed from those shards would vouch for bytes no box ran.")
            return 2
        if kbad:
            err("!! pm_push --bank --on-boxes: the plan and the unit listing disagree. NO ROW")
            err("   WAS WRITTEN and nothing was pushed:" + "".join(f"\n     {x}" for x in kbad))
            return 2
        if missing or extra or uncovered:
            err("!! pm_push --bank --on-boxes: the shards' legs do not add up to a full gate.")
            err("   NO ROW WAS WRITTEN and nothing was pushed.")
            for head, legs in (
                ("in the listing's units and in NO shard's composed-of:", missing),
                ("in a shard's composed-of and in NO unit of the listing:", extra),
                ("declared by FULL_LEGS and covered by no shard:", uncovered),
            ):
                if legs:
                    err(f"   {head}")
                    for leg in legs:
                        err(f"     {leg}")
            return 2
        if red:
            err("RED: pm_push --bank --on-boxes: the gate is RED. NO ROW WAS WRITTEN and nothing")
            err("   was pushed:" + "".join(f"\n     {x}" for x in red))
            err(f"   Each shard's whole log is under {sink}.")
            return 1
        return self.bank_row(rows, onepass, pytest_wall)

    def _passes_agree(
        self, kbad: list[str], label: str, unit: str, passes: str, composed: str
    ) -> None:
        saw = member = ""
        for member in composed.split(","):
            if member == SUITE_LEG:
                saw = "2"
                break
            if member.startswith(f"{SUITE_LEG}/"):
                saw = member.split("/", 1)[1]
                break
        if not saw:
            kbad.append(
                f"{unit}: planned --passes {passes} and the shard's composed-of: names no"
                f" {SUITE_LEG} member at all ({label})"
            )
        elif saw != passes:
            kbad.append(
                f"{unit}: planned --passes {passes} and the shard reports {member} ({label})"
            )

    def _k_agree(self, kbad: list[str], rows: list[tuple[str, str, str, str, str]]) -> None:
        for line in boxes.read_lines(self.listing):
            unit, _needs, shards, _legs = tab_fields(line, 4)
            if not unit:
                continue
            seen = kmax = 0
            for label, lunit, _az, lshard, _p in rows:
                if lunit != unit:
                    continue
                seen += 1
                if shards == "N-capable":
                    if not lshard:
                        kbad.append(f"{unit}: shardable and its shard {label} carries no k/N")
                        continue
                    kk, _, pp = lshard.partition("/")
                    kmax = int(pp)
                    if not 1 <= int(kk) <= int(pp):
                        kbad.append(f"{unit}: shard {lshard} is outside 1..{pp}")
                elif lshard:
                    kbad.append(f"{unit}: indivisible, and {label} was handed --shard {lshard}")
            if seen == 0:
                kbad.append(f"{unit}: the listing declares it and the plan gave it no box")
            if shards == "N-capable" and kmax and seen != kmax:
                kbad.append(
                    f"{unit}: split {kmax} ways and only {seen} of those shards is in the plan"
                )

    def _proof(self, lost: list[str], red: list[str]) -> None:
        from quality.djb.rituals.push import leak_proof_verdict

        bank, sink = self.bank, Path(self.bank.sink)
        proof = sink / "acceptance.proof"
        field = {}
        if bank.accept_id and proof.is_file() and proof.stat().st_size:
            for key in ("seed", "workers", "pass1", "pass2", "map"):
                field[key] = boxes.proof_field_of(proof, key) or ""
        seed, p1, p2 = field.get("seed", ""), field.get("pass1", ""), field.get("pass2", "")
        if not (p1.isdigit() and p2.isdigit()):
            seed = ""
        if not seed:
            none_up = "<none came up>"
            lost.append(
                "acceptance: the leak proof could not be read — one pass was measured and nothing"
                " proved it left nothing behind.\n"
                "              Every pytest shard was planned --passes 1 under ADR gate-1's"
                " amendment, so\n"
                "              the whole-suite two-pass run on the acceptance box IS the belt,"
                " and this\n"
                f"              bank cannot say whether it ran. Box: {bank.accept_id or none_up};"
                " the\n"
                f"              fetch log is {sink}/fetch-proof.log and the box's own log\n"
                f"              is {sink}/acceptance.log."
            )
            return
        workers = field.get("workers") or bank.proof_workers
        out(
            f"acceptance: the leak proof — seed={seed} workers={workers} pass1={p1} pass2={p2}"
            f" map={field.get('map') or '?'}"
        )
        out(f"  from {bank.accept_id}, the whole suite twice under one seed. pass1= and")
        out("  pass2= are the CLAIM this row rests on; map= is a measurement and decides nothing.")
        if p1 == "0" and p2 == "0":
            return
        what, log = ("pass 2", sink / "pass2.log") if p2 != "0" else ("pass 1", sink / "pass1.log")
        _, first = _said(
            boxes.bank_boxes_first_failing, str(log), what, seed, workers=bank.proof_workers
        )
        red.append(
            f"acceptance: the leak proof is RED on {bank.accept_id} — pass1={p1} pass2={p2}\n"
            f"              under seed {seed}. Its whole log is {sink}/acceptance.log.\n"
            f"              {leak_proof_verdict(p1, p2, seed, workers)}\n"
            f"              {first}"
        )

    # --- the row, the harvest, the image, the down ----------------------------------------

    def bank_row(
        self, rows: list[tuple[str, str, str, str, str]], onepass: bool, pytest_wall: int
    ) -> int:
        bank, sink, tree, root = self.bank, Path(self.bank.sink), self.tree, self.root
        labels = ",".join(r[0] for r in rows)
        try:
            sanction = ledger.Sanction(
                "push-wall", "pm_push", f"boxes={self.n} shards={labels}"
            ).check()
        except ledger.Refused:
            raise Died(
                NOTHING_PUSHED,
                "pm_push: the row's sanction would not set — nothing was written and nothing was"
                " pushed.",
            ) from None
        declared, proof = self.declared, ""
        if onepass:
            declared = f",{declared},".replace(f",{SUITE_LEG},", f",{SUITE_LEG}/1,", 1).strip(",")
            proof = (
                self.nform if self.leak_proof == "nightly" else f"acceptance:{bank.accept_id} rc=0"
            )
        try:
            ledger.record_full(
                root,
                tree=tree,
                legs=declared,
                caller="pm-bank",
                sanction=sanction,
                took=pytest_wall,
                proof=proof,
            )
        except (ledger.Refused, ledger.Mismatch, OSError):
            raise Died(
                NOTHING_PUSHED,
                "pm_push: the verdict ledger could not be written. Every shard was green and"
                " nothing\n   was pushed: a green nobody can read is not a verdict.",
            ) from None
        out(f"pm_push --bank --on-boxes: verdict banked for tree {tree}")
        out(f"  caller=pm-bank sanction={sanction.field().removeprefix('sanction=')}")
        if onepass:
            out(f"  legs={declared}")
            out(f"  leak-proof={proof}")
        out("  The pre-push hook will honour it and cost seconds.")
        out("pm_push --bank --on-boxes: bringing the shards' drive rows home.")
        homed = 0
        for label, *_ in rows:
            hid = _read(sink / f"{label}.id")
            if not hid:
                out(
                    f"  drive rows from {label}: LOST (no box id in the sink) — the next bank"
                    " re-drives them"
                )
                continue
            hlog = sink / f"harvest-{label}.log"
            hrc = boxes.vb_call(bank, ["harvest-drives", hid, tree], hlog)
            sys.stdout.write(boxes.read_or(hlog, "") + ("\n" if hlog.stat().st_size else ""))
            if hrc == 0:
                homed += 1
                continue
            why = (
                boxes.reclaim_status_of(str(hlog))
                if boxes.saw_reclaim(str(hlog))
                else f"exit {hrc}"
            )
            out(f"  drive rows from {label}: LOST ({why}) — the next bank re-drives them")
        out(f"  drive rows homed: {homed}/{len(rows)} boxes")
        sys.stdout.flush()
        boxes.bank_boxes_image(bank, self.acheckout, f"tree-{tree[:12]}")
        out("pm_push --bank --on-boxes: taking every box down.")
        sys.stdout.flush()
        if boxes.bank_boxes_down_all(bank) != 0:
            err(f"!! pm_push --bank --on-boxes: the verdict IS banked for {tree} and a box did")
            err("   NOT go down. Nothing was pinned and nothing was pushed: deal with the box")
            err("   first, then ./scripts/pm_push.sh (no --bank) honours the row above.")
            return 2
        return 0


def on_boxes(root: Path, gate: Path, n: int, leak_proof: str) -> int:
    """The `--on-boxes` arm's exit: 0 one row banked · 1 a red shard · 2 a reason named."""
    return Arm(root, gate, n, leak_proof).run()
